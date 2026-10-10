#!/bin/sh
set -e
# Substitute ${BACKEND_URL} into the nginx config template.
# The explicit variable list prevents envsubst from clobbering nginx's own
# $host, $uri, $proxy_add_x_forwarded_for, etc.
envsubst '${BACKEND_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
