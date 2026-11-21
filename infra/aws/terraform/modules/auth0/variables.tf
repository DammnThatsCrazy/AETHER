variable "environment" {
  type        = string
  description = "Deployment environment (staging | production)"
}

variable "api_audience" {
  type        = string
  description = "Audience identifier for the AETHER API resource server"
  default     = "https://api.aether.io"
}

variable "mcp_resource_uri" {
  type        = string
  description = "Exact public MCP resource URI, or empty when remote MCP OAuth is disabled."
  default     = ""
  validation {
    condition     = var.mcp_resource_uri == "" || can(regex("^https://[^/?#]+/[A-Za-z0-9/_-]+$", var.mcp_resource_uri))
    error_message = "mcp_resource_uri must be an exact HTTPS MCP resource URL without query or fragment."
  }
}

variable "enable_mcp_client_registration" {
  type        = bool
  description = "Open MCP client registration (Dynamic Client Registration and Client ID Metadata Documents) with a read-only third-party default grant on the MCP audience. Requires mcp_resource_uri."
  default     = false
  validation {
    condition     = !var.enable_mcp_client_registration || var.mcp_resource_uri != ""
    error_message = "enable_mcp_client_registration requires remote MCP OAuth (mcp_resource_uri)."
  }
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

variable "enable_social_connections" {
  type        = bool
  description = "Create optional Google, Apple, Twitter, Microsoft, and Slack connections only when their provider credentials are ready."
  default     = false
}

variable "social_providers" {
  type        = list(string)
  description = "Which social connections to create when enable_social_connections is true (google, apple, twitter, microsoft, slack). The root module lists only providers whose credentials are provisioned."
  default     = ["google", "apple", "twitter", "microsoft", "slack"]

  validation {
    condition     = alltrue([for p in var.social_providers : contains(["google", "apple", "twitter", "microsoft", "slack"], p)])
    error_message = "social_providers may only contain google, apple, twitter, microsoft and slack."
  }
}

# ── Social connection credentials ─────────────────────────────────────────
# All social vars default to "" so the module can be applied without them;
# the connections are created but remain unconfigured until credentials are
# supplied from the Auth0 Dashboard / respective developer portals.

variable "google_client_id" {
  type      = string
  default   = ""
  sensitive = true
}

variable "google_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "apple_client_id" {
  type      = string
  default   = ""
  sensitive = true
}

variable "apple_client_secret" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Apple private key (.p8 content)"
}

variable "apple_team_id" {
  type    = string
  default = ""
}

variable "apple_key_id" {
  type    = string
  default = ""
}

variable "twitter_consumer_key" {
  type      = string
  default   = ""
  sensitive = true
}

variable "twitter_consumer_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "microsoft_client_id" {
  type      = string
  default   = ""
  sensitive = true
}

variable "microsoft_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "slack_client_id" {
  type      = string
  default   = ""
  sensitive = true
}

variable "slack_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}
