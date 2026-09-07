# LeaseLurker

LeaseLurker ist ein ausschließlich lesendes Webinterface für aktive IPv4-Leases
eines Kea-DHCP-Servers. Enduser können anhand eines Hostname- oder
MAC-Adressfragments die aktuelle IP-Adresse ihres Rechners ermitteln. Die
Listenansicht gruppiert freigegebene Leases nach Subnetz.

> **Hinweis zum Projektstatus:** LeaseLurker ist ein Arbeitsprojekt, das im
> Rahmen der beruflichen Tätigkeit am Karlsruher Institut für Technologie (KIT)
> entwickelt wurde.

## Voraussetzungen

- Python 3.14 für lokale Entwicklung
- Poetry 2.4 oder neuer
- Kea Control Agent mit aktivierten Hooks `lease_cmds` und `subnet_cmds`
- Docker mit Compose für den vorgesehenen Produktivbetrieb

Kea muss die Befehle `lease4-get-all` und `subnet4-list` über den Dienst
`dhcp4` bereitstellen. LeaseLurker besitzt bewusst keine schreibenden
Kea-Kommandos.

## Lokale Installation

```bash
poetry install
cp config.example.yaml config.yaml
LEASELURKER_CONFIG=./config.yaml poetry run lease-lurker
```

Danach ist die Anwendung unter <http://localhost:8080> erreichbar.

### Entwicklung ohne Kea

Für lokale UI- und Integrationstests steht ein kleiner Kea-Control-Agent-Mock mit
Beispielsubnetzen und -leases bereit:

```bash
cp config.example.yaml config.yaml
docker compose -f compose.yaml -f compose.build.yaml -f compose.mock.yaml up --build
```

LeaseLurker verwendet dabei automatisch `http://mock-kea:8000/`. Subnetz 1 ist
sichtbar und enthält zwei aktive Beispielleases; Subnetz 2 bleibt entsprechend der
Beispielkonfiguration verborgen. Der Mock implementiert ausschließlich
`list-commands`, `status-get`, `subnet4-list` und `lease4-get-all` und ist nicht für
Produktivbetrieb vorgesehen.

## Konfiguration

Die YAML-Datei legt Cache, Sprache und sichtbare Subnetze fest. Nicht aufgeführte
und mit `visible: false` konfigurierte Subnetze bleiben verborgen. Anzeigenamen
können den von Kea gelieferten Namen überschreiben.

Deploymentwerte werden bevorzugt per Umgebung gesetzt:

| Variable | Bedeutung |
|---|---|
| `LEASELURKER_CONFIG` | Pfad zur YAML-Datei |
| `LEASELURKER_KEA_URL` | URL des Kea Control Agent |
| `LEASELURKER_KEA_USERNAME` | Optionaler Basic-Auth-Benutzer |
| `LEASELURKER_KEA_PASSWORD` | Optionales Basic-Auth-Passwort |
| `LEASELURKER_LOG_LEVEL` | Python-Log-Level, standardmäßig `INFO` |

Zugangsdaten gehören nicht in die YAML-Beispieldatei oder das Image. Benutzername
und Passwort müssen immer gemeinsam gesetzt werden.

## Qualität und Tests

```bash
poetry run ruff format .
poetry run ruff check .
poetry run mypy src
poetry run pytest
poetry run pip-audit
```

## Offline-Herstellerdaten

Die Anwendung führt zur Laufzeit keine Herstellerabfragen im Internet aus. Die
gebündelte Datenbank wird aus den öffentlichen IEEE-Registern MA-L, MA-M und MA-S
erzeugt:

```bash
poetry run python scripts/update_ieee_vendors.py
```

Änderungen der erzeugten Datei werden geprüft und zusammen mit dem Projekt
versioniert. Quelle: [IEEE Registration Authority](https://standards.ieee.org/products-programs/regauth/).

## Container

```bash
cp config.example.yaml config.yaml
docker compose pull
docker compose up -d
```

Kea läuft als Dienst auf dem Docker-Host. Compose bildet dafür
`host.docker.internal` auf `host-gateway` ab. Der Container läuft ohne Root-Rechte,
ohne Linux-Capabilities und mit schreibgeschütztem Dateisystem.

Das öffentliche Multi-Arch-Image für AMD64 und ARM64 liegt unter
`ghcr.io/phill93/leaselurker`. Stabile Releases erhalten vollständige SemVer-,
Minor-, Major- und `latest`-Tags. Für einen lokalen Image-Build:

```bash
docker compose -f compose.yaml -f compose.build.yaml up --build
```

Veröffentlichte Images enthalten SBOM und Build-Provenance und werden über
GitHub OIDC keyless signiert. Eine Signatur kann mit Cosign geprüft werden:

```bash
cosign verify ghcr.io/phill93/leaselurker:latest \
  --certificate-identity-regexp '^https://github.com/Phill93/LeaseLurker/.github/workflows/release-image.yml@refs/tags/v' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com'
```

## Release

Die Paketversion wird ausschließlich in `pyproject.toml` gepflegt und von der
Anwendung aus den installierten Metadaten gelesen. Für einen Release:

1. Änderungen unter `Unreleased` in `CHANGELOG.md` einer datierten Version
   zuordnen.
2. `poetry check --lock`, Ruff, mypy, pytest, `pip-audit` und den Container-Build
   erfolgreich ausführen.
3. Wheel und sdist mit `poetry build` erzeugen und aus dem Wheel testen.
4. Den geprüften Commit mit einem signierten Tag `v<Version>` markieren und ein
   GitHub-Release veröffentlichen. Der Release-Workflow scannt AMD64 und ARM64
   separat und veröffentlicht das Image nur nach erfolgreichen Prüfungen.

## Architektur und Betrieb

Die Adapterentscheidung ist in
[`docs/adr/0001-read-only-adapter-architecture.md`](docs/adr/0001-read-only-adapter-architecture.md)
dokumentiert. `/health/live` prüft den Prozess; `/health/ready` berücksichtigt Kea
und den letzten brauchbaren Snapshot. Der In-Memory-Cache ist pro Prozess, daher
startet das ausgelieferte Image genau einen Uvicorn-Prozess.

## Copyright, Urheber und Lizenz

- **Copyright-Inhaber:** Karlsruher Institut für Technologie (KIT)
- **Urheber:** Daniel Bacher
- **Lizenz:** MIT License, siehe [LICENSE](LICENSE)

Copyright © 2026 Karlsruher Institut für Technologie (KIT). LeaseLurker darf
unter den Bedingungen der MIT-Lizenz verwendet, verändert und weitergegeben
werden. Pflege und Issues erfolgen über das Projekt-Repository.
