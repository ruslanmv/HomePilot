#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstraps an Oracle Cloud Infrastructure "Always Free" compute instance for
# the HomePilot web deployment. OS-aware — supports both Always Free families:
#   - Oracle Linux 8/9  (dnf + firewalld)  e.g. VM.Standard.A1.Flex, user "opc"
#   - Ubuntu            (apt + iptables)   e.g. VM.Standard.E2.1.Micro, user "ubuntu"
#
# Tuned for the small Always Free shapes (as little as 1 OCPU / 1–6 GB RAM):
# creates a swap file and applies conservative VM tuning so a memory spike from
# an image pull or a request burst doesn't OOM-kill the container.
#
# Opening ports here is only half the job — you must ALSO add ingress rules for
# TCP 80 and 443 to the subnet's Security List / NSG in the OCI console.
# See oracle/README.md.
#
# Tunables (override via environment):
#   DEPLOY_USER  account that owns /opt/homepilot and runs docker (default: sudo user)
#   SWAP_SIZE    swap file size, e.g. 2G / 4G (default: 4G; set to 0 to skip)

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this script as root: sudo bash oracle/install.sh" >&2
  exit 1
fi

# The unprivileged account that will own /opt/homepilot and run docker compose.
# Defaults to whoever invoked sudo (opc on Oracle Linux, ubuntu on Ubuntu).
DEPLOY_USER="${DEPLOY_USER:-${SUDO_USER:-}}"
SWAP_SIZE="${SWAP_SIZE:-4G}"

# shellcheck disable=SC1091
. /etc/os-release
OS_ID="${ID:-}"
OS_LIKE="${ID_LIKE:-}"

# ---------------------------------------------------------------------------
# Docker installation (OS-aware)
# ---------------------------------------------------------------------------
install_docker_rhel() {
  dnf -y install git curl ca-certificates dnf-plugins-core
  # dnf-3 uses `config-manager --add-repo`; newer dnf5 uses `addrepo`.
  dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null \
    || dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/centos/docker-ce.repo
  dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

install_docker_debian() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl git iptables-persistent
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

# ---------------------------------------------------------------------------
# Host firewall — open 80/443 (OS-aware)
# ---------------------------------------------------------------------------
open_ports_firewalld() {
  firewall-cmd --permanent --add-service=http
  firewall-cmd --permanent --add-service=https
  firewall-cmd --reload
}

open_ports_iptables() {
  # Oracle's images ship a default INPUT policy that REJECTs inbound traffic via
  # a rule near the end of the chain. Insert ACCEPT rules for HTTP/HTTPS ahead
  # of that reject rule, then persist across reboots.
  open_port() {
    local port="$1"
    if ! iptables -C INPUT -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
      iptables -I INPUT 5 -p tcp --dport "$port" -m conntrack --ctstate NEW -j ACCEPT
    fi
  }
  open_port 80
  open_port 443
  if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save
  elif command -v service >/dev/null 2>&1 && [[ -d /etc/iptables ]]; then
    iptables-save > /etc/iptables/rules.v4 || true
  fi
}

if command -v dnf >/dev/null 2>&1 || [[ "$OS_ID" == "ol" || "$OS_LIKE" == *rhel* || "$OS_LIKE" == *fedora* ]]; then
  echo "Detected RHEL family (${PRETTY_NAME:-$OS_ID}); using dnf + firewalld."
  install_docker_rhel
  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
    open_ports_firewalld
  else
    open_ports_iptables
  fi
else
  echo "Detected Debian family (${PRETTY_NAME:-$OS_ID}); using apt + iptables."
  install_docker_debian
  open_ports_iptables
fi

# ---------------------------------------------------------------------------
# Swap — critical on the small Always Free shapes (1–6 GB RAM)
# ---------------------------------------------------------------------------
if [[ "$SWAP_SIZE" != "0" ]] && ! swapon --show=NAME --noheadings | grep -q '/swapfile'; then
  echo "Creating ${SWAP_SIZE} swap file at /swapfile..."
  if ! fallocate -l "$SWAP_SIZE" /swapfile 2>/dev/null; then
    # fallocate can fail on some filesystems — fall back to dd (GiB granularity)
    dd if=/dev/zero of=/swapfile bs=1M count=$(( ${SWAP_SIZE%G} * 1024 )) status=none
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------------------------------------------------------------------------
# VM tuning for low-memory hosts — prefer RAM, but let swap absorb spikes.
# ---------------------------------------------------------------------------
cat > /etc/sysctl.d/99-homepilot.conf <<'SYSCTL'
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.overcommit_memory = 1
SYSCTL
sysctl --quiet -p /etc/sysctl.d/99-homepilot.conf || true

# ---------------------------------------------------------------------------
# Deploy user: run docker without sudo + own the app directory
# ---------------------------------------------------------------------------
install -d -m 0755 /opt/homepilot
if [[ -n "$DEPLOY_USER" ]] && id "$DEPLOY_USER" >/dev/null 2>&1; then
  usermod -aG docker "$DEPLOY_USER"
  chown -R "$DEPLOY_USER":"$DEPLOY_USER" /opt/homepilot
  echo "Added '$DEPLOY_USER' to the docker group and gave it /opt/homepilot."
  echo "NOTE: '$DEPLOY_USER' must open a NEW SSH session for docker-group"
  echo "      membership to take effect (GitHub Actions reconnects each run)."
fi

echo
echo "Instance bootstrap complete."
echo "Next steps:"
echo "  1. Add ingress rules for TCP 80 and 443 in the OCI Security List / NSG."
echo "  2. Copy oracle/ into /opt/homepilot, create .env from .env.example."
echo "  3. Run: cd /opt/homepilot && bash deploy.sh"
