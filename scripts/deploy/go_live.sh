#!/usr/bin/env bash
# =============================================================================
# AETHER — Website Go-Live Orchestrator
#
# Consolidated script that walks every step from an empty AWS account to live
# websites at olympuslabsml.com:
#
#   olympuslabsml.com        → Squarespace apex/redirect surface
#   www.olympuslabsml.com    → Amplify (Olympus Labs marketing)
#   aether.olympuslabsml.com → Amplify (product marketing)
#   docs.olympuslabsml.com   → Amplify (developer docs)
#   app.olympuslabsml.com    → Amplify (customer dashboard)
#   status.olympuslabsml.com → Amplify (public status)
#   api.olympuslabsml.com    → ALB (backend API)
#
# Run interactively — the script pauses for manual steps (console actions,
# credential entry). It will NOT auto-apply anything destructive.
#
# Prerequisites:
#   - AWS CLI v2 with credentials for the target account
#   - Terraform >= 1.7
#   - Docker (for backend image build)
#   - Auth0 tenant credentials (exported as env vars)
#   - Squarespace DNS access for the apex redirect and Amplify CNAME records
#
# Usage:
#   cd "$(git rev-parse --show-toplevel)"
#   ./scripts/deploy/go_live.sh [--profile production-lean] [--region us-east-1]
# =============================================================================
set -euo pipefail

# ─── Defaults ────────────────────────────────────────────────────────────────
PROFILE="${PROFILE:-production-lean}"
REGION="${AWS_REGION:-us-east-1}"
DOMAIN="olympuslabsml.com"
API_DOMAIN="api.${DOMAIN}"
TF_DIR="deploy/aws/terraform"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="${2:?}"; shift 2 ;;
    --region)  REGION="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

# ─── Helpers ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

step()  { echo -e "\n${CYAN}═══ STEP $1: $2 ${NC}"; }
info()  { echo -e "${GREEN}    ✓ $1${NC}"; }
warn()  { echo -e "${YELLOW}    ⚠ $1${NC}"; }
err()   { echo -e "${RED}    ✗ $1${NC}"; }
pause() { echo -e "\n${YELLOW}    ▸ $1${NC}"; read -rp "    Press ENTER when ready..." _; }

# ─── Pre-flight ──────────────────────────────────────────────────────────────
echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║              AETHER — Website Go-Live Orchestrator              ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  Profile : ${PROFILE}                                          "
echo "║  Region  : ${REGION}                                           "
echo "║  Domain  : ${DOMAIN}                                           "
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

command -v aws >/dev/null 2>&1 || { err "AWS CLI not found"; exit 1; }
command -v terraform >/dev/null 2>&1 || { err "Terraform not found"; exit 1; }

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
info "AWS account: ${ACCOUNT_ID}"
info "Region: ${REGION}"

# ─── Check env vars ─────────────────────────────────────────────────────────
for var in AUTH0_DOMAIN AUTH0_CLIENT_ID AUTH0_CLIENT_SECRET; do
  if [ -z "${!var:-}" ]; then
    err "${var} is not set"
    echo "    Export Auth0 management credentials before running:"
    echo "      export AUTH0_DOMAIN=your-tenant.us.auth0.com"
    echo "      export AUTH0_CLIENT_ID=..."
    echo "      export AUTH0_CLIENT_SECRET=..."
    exit 1
  fi
done
info "Auth0 credentials present"

# =============================================================================
step 1 "Bootstrap Terraform State Backend"
# =============================================================================
STATE_BUCKET="aether-tfstate-${ACCOUNT_ID}"
LOCK_TABLE="aether-tf-locks"

if aws s3api head-bucket --bucket "${STATE_BUCKET}" 2>/dev/null; then
  info "State bucket already exists: ${STATE_BUCKET}"
else
  echo "    Creating state bucket and lock table..."
  cd "${REPO_ROOT}/${TF_DIR}/bootstrap"
  ./bootstrap_state_backend.sh \
    --bucket "${STATE_BUCKET}" \
    --lock-table "${LOCK_TABLE}" \
    --region "${REGION}"
  cd "${REPO_ROOT}"
  info "State backend created"
fi

# =============================================================================
step 2 "ACM Certificate"
# =============================================================================
echo "    Checking for existing ACM certificate for *.${DOMAIN}..."

CERT_ARN="$(aws acm list-certificates --region "${REGION}" \
  --query "CertificateSummaryList[?DomainName=='${API_DOMAIN}' || DomainName=='*.${DOMAIN}' || DomainName=='${DOMAIN}'].CertificateArn | [0]" \
  --output text 2>/dev/null || echo "None")"

if [ "${CERT_ARN}" != "None" ] && [ -n "${CERT_ARN}" ]; then
  info "Found certificate: ${CERT_ARN}"
else
  warn "No existing certificate found for ${DOMAIN}"
  echo "    Requesting a wildcard certificate..."
  CERT_ARN="$(aws acm request-certificate \
    --domain-name "${DOMAIN}" \
    --subject-alternative-names "*.${DOMAIN}" \
    --validation-method DNS \
    --region "${REGION}" \
    --query CertificateArn --output text)"
  info "Certificate requested: ${CERT_ARN}"
  echo ""
  echo "    DNS validation records needed. Run:"
  echo "      aws acm describe-certificate --certificate-arn ${CERT_ARN} --region ${REGION} \\"
  echo "        --query 'Certificate.DomainValidationOptions'"
  echo ""
  pause "Add the DNS validation CNAME records at your domain registrar, then wait for validation"

  echo "    Waiting for certificate validation (this may take a few minutes)..."
  aws acm wait certificate-validated --certificate-arn "${CERT_ARN}" --region "${REGION}" \
    || { warn "Timed out waiting — check certificate status manually"; }
fi

info "ACM certificate ARN: ${CERT_ARN}"

# =============================================================================
step 3 "Terraform Init"
# =============================================================================
cd "${REPO_ROOT}/${TF_DIR}"

terraform init \
  -backend-config="bucket=${STATE_BUCKET}" \
  -backend-config="dynamodb_table=${LOCK_TABLE}" \
  -backend-config="key=profiles/${PROFILE}/terraform.tfstate" \
  -backend-config="region=${REGION}" \
  -backend-config="encrypt=true"

info "Terraform initialized"

# =============================================================================
step 4 "Phase A — Create ECR Registries"
# =============================================================================
echo "    Creating ECR repositories first (needed for image digests)..."

terraform apply \
  -target=module.ecr \
  -var-file="profiles/${PROFILE}.tfvars" \
  -var="acm_certificate_arn=${CERT_ARN}" \
  -var="alert_email=ops@olympuslabsml.com" \
  -var="backend_image_digest=sha256:0000000000000000000000000000000000000000000000000000000000000000" \
  -auto-approve \
  2>&1

info "ECR repositories created"

# =============================================================================
step 5 "Build & Push Backend Image"
# =============================================================================
ECR_BASE="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

echo "    Authenticating to ECR..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin "${ECR_BASE}"

echo "    Building backend image..."
cd "${REPO_ROOT}/services/backend"
docker build -t aether-backend .

docker tag aether-backend:latest "${ECR_BASE}/aether-backend:latest"
docker push "${ECR_BASE}/aether-backend:latest"

BACKEND_DIGEST="$(aws ecr describe-images --repository-name aether-backend \
  --image-ids imageTag=latest --region "${REGION}" \
  --query 'imageDetails[0].imageDigest' --output text)"
info "Backend image digest: ${BACKEND_DIGEST}"

# =============================================================================
step 6 "GitHub Token for Amplify"
# =============================================================================
echo "    Amplify needs a GitHub personal access token to pull code from your repo."
echo "    Create one at: github.com → Settings → Developer Settings → Personal Access Tokens"
echo "    Scope needed: 'repo' (full control of private repositories)"
echo ""
if [ -n "${AMPLIFY_GITHUB_TOKEN:-}" ]; then
  info "AMPLIFY_GITHUB_TOKEN already set"
  GH_TOKEN="${AMPLIFY_GITHUB_TOKEN}"
else
  read -rsp "    Enter GitHub personal access token (input hidden): " GH_TOKEN
  echo ""
fi

if [ -z "${GH_TOKEN}" ]; then
  warn "No token provided — Amplify apps will be created but cannot pull from a private repo"
  GH_TOKEN_ARGS=()
else
  info "GitHub token captured"
  GH_TOKEN_ARGS=(-var="amplify_github_access_token=${GH_TOKEN}")
fi

# =============================================================================
step 7 "Plan & Apply — Full Infrastructure (without DNS)"
# =============================================================================
cd "${REPO_ROOT}/${TF_DIR}"

echo "    Planning full infrastructure (squarespace_hosted_zone_enabled=false)..."
echo "    This creates: VPC, ALB, ECS, Aurora, DynamoDB, SQS/SNS, Amplify, Secrets, Monitoring"

terraform plan \
  -var-file="profiles/${PROFILE}.tfvars" \
  -var="acm_certificate_arn=${CERT_ARN}" \
  -var="alert_email=ops@olympuslabsml.com" \
  -var="backend_image_digest=${BACKEND_DIGEST}" \
  -var="squarespace_hosted_zone_enabled=false" \
  "${GH_TOKEN_ARGS[@]}" \
  -out=tfplan

echo ""
echo "    Review the plan above carefully."
pause "Type ENTER to apply, or Ctrl-C to abort"

terraform apply tfplan
info "Core infrastructure deployed"

# Capture outputs
ALB_DNS="$(terraform output -raw alb_dns)"
AMPLIFY_DOMAINS="$(terraform output -json amplify_default_domains)"
info "ALB DNS: ${ALB_DNS}"
info "Amplify domains: ${AMPLIFY_DOMAINS}"

# =============================================================================
step 8 "Post-Deploy: Secrets & Migrations"
# =============================================================================
echo "    Confirm SNS email subscription (check your inbox for ${alert_email:-ops@olympuslabsml.com})"
echo ""
echo "    Inject secrets into Secrets Manager:"
echo "      aws secretsmanager put-secret-value --secret-id aether/jwt-secret --secret-string 'YOUR_KEY'"
echo "      aws secretsmanager put-secret-value --secret-id aether/auth0-client-secret --secret-string '...'"
echo ""
echo "    Run database migrations (from within the VPC or using ECS Exec)."
pause "Complete the post-deploy steps above"

# =============================================================================
step 9 "Verify Amplify Apps"
# =============================================================================
echo "    Your Amplify apps should now be building from the main branch."
echo "    Default domains (accessible immediately, no custom domain needed):"
echo ""
echo "    Check the Amplify Console in the AWS Management Console to:"
echo "      1. Verify builds are running"
echo "      2. Confirm the default domains load"
echo "      3. Trigger a manual build if needed"
echo ""
echo "    Amplify default domains:"
echo "    ${AMPLIFY_DOMAINS}"
pause "Verify Amplify apps are building and serving"

# =============================================================================
step 10 "Squarespace DNS + Amplify custom domains"
# =============================================================================
echo ""
echo "    Squarespace remains authoritative for the first release."
echo "    Add the Amplify custom-domain CNAME targets from:"
echo "      terraform output -json amplify_custom_domain_dns_records"
echo "    Required records:"
echo "      - www.olympuslabsml.com        → Olympus Amplify association"
echo "      - aether.olympuslabsml.com     → Amplify"
echo "      - docs.olympuslabsml.com       → Amplify"
echo "      - app.olympuslabsml.com        → Amplify"
echo "      - status.olympuslabsml.com     → Amplify"
echo "      - api.olympuslabsml.com        → ALB (${ALB_DNS})"
echo "    Keep olympuslabsml.com on the Squarespace apex redirect to www."
echo ""
echo "    Before proceeding, go to Squarespace:"
echo "      Settings → Domains → DNS Settings"
echo "      Add the CNAME records returned by the Terraform output"
echo ""
pause "Add the CNAME records in Squarespace and wait for DNS propagation"

# =============================================================================
step 11 "Squarespace Domain Verification"
# =============================================================================
echo ""
echo "    In Squarespace:"
echo "      1. Confirm the apex redirect points to www.${DOMAIN}"
echo "      2. Confirm the five Amplify CNAMEs resolve"
echo "      3. Confirm Amplify custom-domain certificates are issued"
echo "      4. Confirm the API CNAME and status health origin"
echo ""
pause "Verify the Squarespace and Amplify domain surfaces"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                    🎉  WEBSITES ARE LIVE  🎉                    ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║                                                                 ║"
echo "║  Marketing:  https://www.${DOMAIN}             (Amplify)         "
echo "║  Apex:       https://${DOMAIN}           (Squarespace redirect) "
echo "║  Product:    https://aether.${DOMAIN}         (Amplify)         "
echo "║  Docs:       https://docs.${DOMAIN}           (Amplify)         "
echo "║  App:        https://app.${DOMAIN}            (Amplify)         "
echo "║  API:        https://api.${DOMAIN}            (ALB)             "
echo "║                                                                 ║"
echo "║  ALB DNS:    ${ALB_DNS}                                         "
echo "║                                                                 ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Outputs saved. Run 'terraform output' for full details."
