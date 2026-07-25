variable "environment" {
  type        = string
  description = "Deployment environment (staging | production)"
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
