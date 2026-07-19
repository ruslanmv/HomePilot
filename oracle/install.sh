#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstraps an Oracle Cloud Infrastructure "Always Free" compute instance
# (Ubuntu) for the HomePilot web deployment. Works on both Always Free shapes:
#   - VM.Standard.A1.Flex    (Ampere ARM / aarch64, up to 4 OCPU / 24 GB)
#   - VM.Standard.E2.1.Micro (AMD x86_64, 1 GB)
#
# Note: opening ports here is only half the job. You must ALSO add ingress
# rules for TCP 80 and 443 to the instance subnet's Security List (or Network
# Security Group) in the OCI console. See oracle/README.md.

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root: sudo bash oracle/install.sh" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git iptables-persistent

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

# Oracle's Ubuntu images ship a default INPUT policy that REJECTs inbound
# traffic (via a rule near the end of the chain). Insert ACCEPT rules for HTTP
# and HTTPS ahead of that reject rule so Caddy can serve traffic and complete
# the ACME challenge, then persist them across reboots.
open_port() {
  local port="$1"
  if ! iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 5 -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
  fi
}
open_port 80
open_port 443
netfilter-persistent save

install -d -m 0750 /opt/homepilot

echo "Instance bootstrap complete."
echo "Next: add ingress rules for TCP 80 and 443 in the OCI Security List,"
echo "copy oracle/ to /opt/homepilot, create .env, then run deploy.sh."
