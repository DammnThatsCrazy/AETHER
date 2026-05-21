output "aether_client_id" {
  description = "Auth0 client ID for the Aether SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.aether.client_id
}

output "kyber_client_id" {
  description = "Auth0 client ID for the Kyber SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.kyber.client_id
}

output "auth0_domain" {
  description = "Auth0 tenant domain — use as VITE_AUTH0_DOMAIN build arg"
  value       = var.auth0_domain
}

output "api_audience" {
  description = "API resource server audience — use as VITE_AUTH0_AUDIENCE build arg"
  value       = auth0_resource_server.api.identifier
}
