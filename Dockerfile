# syntax=docker/dockerfile:1

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── Layer 1: INDI PPA + system packages ──────────────────────────────
# The INDI PPA uses DEB822 format with an inline GPG key.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY <<'INDI_SOURCES' /etc/apt/sources.list.d/indi.sources
Types: deb
URIs: https://ppa.launchpadcontent.net/mutlaqja/ppa/ubuntu
Suites: noble
Components: main
Signed-By:
 -----BEGIN PGP PUBLIC KEY BLOCK-----
 .
 mQINBGYzk+oBEADBRiC3rHd2QZQCyPbO8G02p2sMKa66pvJx/eQr4LPQt+RB7QJv
 rnJjUO5A6a37Ve1uI6hKEGW91saMSFR7Va9KXZgoL3U+W+1epIGV8OCVCqvpFrzF
 RJaYjSiXZbeJOvN1iTRj5U8/kG+HcRTYUlnhKEgwh9/2EG8i+Wu9s+ABLVvYEHFF
 zMgX5MZHQgeBTRFctHBMpZg1bze6/a6pP5MyTQkL99MmrOnZ8PfrSZSE5x9AovJs
 Z2EIcDctnwO0sAnFPZ82oyHD3lPcQqmQhc03GB2bWxoR/474G2sjp+azyXV+T75f
 KZqZZ07IvrZJ68h+iRt9wm8XhagvzTV180PaS7ZAJCuTdJIJueSvB0lbetxhRlcj
 8uWx45ZMNW0Ncoo5pEMuTkU7sIYnmhNQzBHMovBlaeCcmKu8vGJR0RQP9g8ytfGJ
 87bx2aNRkgkyboSGOU3cqS6faUAWZNvAy2eOUahjuDRxvFvMnn8TyCaV3ewjLlI5
 iLbvsQldztp31+u2cDCwxd9PdPC9+P7LzODiVtlxDAUUSNl4VVsv/CgID3wkSjCA
 BtkVS3Kje7Pe8XGiKFB4TJo19zoiEBbtY/vmDE4y+k8Up8XFK+2krmy9AEGByy7t
 g3L8+56VoLoRma/fS5jWipo9SWCV1GlRxnNuslxAqnq58gP3epwgCjfRDwARAQAB
 tB5MYXVuY2hwYWQgUFBBIGZvciBKYXNlbSBNdXRsYXGJAk4EEwEKADgWIQT4HU+M
 FpdciILXs4Mz5y1EpfLpYgUCZjOT6gIbAwULCQgHAgYVCgkICwIEFgIDAQIeAQIX
 gAAKCRAz5y1EpfLpYk5nD/47CIBejEVPEDX1vHD/uTQMQGNfw4nAn4A54ODbOveh
 f/GOl7g+ecLA0FMJLJuuuLeMmKdozAZua/U97DJYi3FhlvyHTz/b6k9HVSabuE3B
 0ssRA7wHo1Exlkpk5LATDjaFqevRhWzHwI8yc3b+oV89q3kqiLI4CETkrp5vxptY
 EFGZjsMe9Ph8/5dLwaq9BaZKeJ3ycisP57oj4svDmiflRXZE6umjd9DLRgCNLZft
 w5+hMWmvNxaDQEWoruC1jlhRHe5LMQkZDO8G23icrR0Xj9uYGAT2MmsBa32x1EOa
 uDjYJafeu74H0+PjVFIxkYb3ne7EURjy8tTE96qU7MrsfJeX8WSEiWP98EUhxcD6
 ivJIEKZNLaWOfzDmS2dQBurJO6UfAfYRgSy5qtjiugh6ktxNmvjBGpoExXuVC8BR
 DQiZGf5JTqZtq1ES6nfWBOvT+gzGggqqNGU8uoLkqIGJyzahIK5RVTlBOhBpiWqV
 leFNihW/1H7kr6BanxIY61n4HI7vb3LmcNAQTNmxhuCdW2cvVk14tyU9L5Wphjm+
 ZF4sXpOakuPQ1pP76dYw6W9lhqF88RFfgdLs+ymem1zDOyz7EzXNMbTsj0YRnJyT
 bLqQNMA9hViX9e3APnP1aG3llD6d4QL8pBicQ2h3dwLrytbA+ttLdqlRrtln/XeO
 mw==
 =d74M
 -----END PGP PUBLIC KEY BLOCK-----
INDI_SOURCES

ARG INDI_VERSION=2.1.9+202602201352~ubuntu24.04.1
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        indi-bin=${INDI_VERSION} \
        libindi1=${INDI_VERSION} \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# ── Layer 2: ASTAP CLI ──────────────────────────────────────────────
RUN curl -fSL -o astap_cli_amd64.zip \
        "https://sourceforge.net/projects/astap-program/files/linux_installer/astap_command-line_version_Linux_amd64.zip/download" \
    && echo "fca72cff7cf7db2811262710d53e88242d6ef2e74eac444fef95b73244f37e0f astap_cli_amd64.zip" | sha256sum -c - \
    && unzip astap_cli_amd64.zip -d /usr/bin/ \
    && rm astap_cli_amd64.zip

# ── Layer 3: ASTAP D05 star database ────────────────────────────────
RUN curl -fSL -o d05_star_database.deb \
        "https://sourceforge.net/projects/astap-program/files/star_databases/d05_star_database.deb/download" \
    && echo "e00b276e86c5673aef862d4fa093e739bd58cad267af916756409770fd0bd8eb d05_star_database.deb" | sha256sum -c - \
    && dpkg -i d05_star_database.deb \
    && rm d05_star_database.deb
ENV ASTAP_DB=/opt/astap

# ── Layer 4: Tycho-2 catalog (~120 MB from CDS Strasbourg) ──────────
WORKDIR /opt/astrolabe
COPY scripts/install-tycho2.sh scripts/install-tycho2.sh
RUN bash scripts/install-tycho2.sh

# ── Layer 5: uv + Python 3.11 + project dependencies ────────────────
ENV PATH="/root/.local/bin:$PATH"
RUN curl --proto "=https" --tlsv1.2 -LsSfO https://github.com/astral-sh/uv/releases/download/0.10.4/uv-installer.sh \
    && echo "169fd7c68bdd40f80ab25635b1e10adfc8cef58b4935017e8560c87639d4544c uv-installer.sh" | sha256sum -c - \
    && sh uv-installer.sh \
    && rm uv-installer.sh

COPY pyproject.toml uv.lock ./
RUN uv venv --python 3.11 .venv \
    && uv sync --extra dev --extra tools

# ── Layer 6: Application code ───────────────────────────────────────
# .dockerignore excludes tycho2/, so COPY won't overwrite downloaded data
COPY . .
RUN chmod +x scripts/integration-entrypoint.sh

# ── Environment ─────────────────────────────────────────────────────
ENV ASTROLABE_INDI_INTEGRATION=1
ENV ASTAP_CLI=astap_cli

ENTRYPOINT ["scripts/integration-entrypoint.sh"]
CMD ["--integration"]
