variable "environment" {
  type        = string
  description = "Deployment environment (staging | production)"
}

variable "auth0_domain" {
  type        = string
  description = "Auth0 tenant domain (e.g. your-tenant.auth0.com)"
}

variable "auth0_management_client_id" {
  type        = string
  description = "Client ID of the Terraform M2M application in Auth0"
  sensitive   = true
}

variable "auth0_management_client_secret" {
  type        = string
  description = "Client secret of the Terraform M2M application in Auth0"
  sensitive   = true
}

variable "api_audience" {
  type        = string
  description = "Audience identifier for the AETHER API resource server"
  default     = "https://api.aether.io"
}

# ── Aether SPA ────────────────────────────────────────────────────────────

variable "aether_callback_urls" {
  type        = list(string)
  description = "Allowed OAuth callback URLs for the Aether SPA"
}

variable "aether_logout_urls" {
  type        = list(string)
  description = "Allowed logout return URLs for the Aether SPA"
}

variable "aether_web_origins" {
  type        = list(string)
  description = "Allowed web origins (CORS) for the Aether SPA"
}

# ── Kyber SPA ─────────────────────────────────────────────────────────────

variable "kyber_callback_urls" {
  type        = list(string)
  description = "Allowed OAuth callback URLs for the Kyber SPA"
}

variable "kyber_logout_urls" {
  type        = list(string)
  description = "Allowed logout return URLs for the Kyber SPA"
}

variable "kyber_web_origins" {
  type        = list(string)
  description = "Allowed web origins (CORS) for the Kyber SPA"
}
