# Changelog

Alle wesentlichen Änderungen dieses Projekts werden in dieser Datei dokumentiert.
Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/)
und die Versionierung an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Behoben

- Docker Compose reicht die Basic-Auth-Zugangsdaten für den Kea Control Agent an
  den LeaseLurker-Container weiter.
- Der lokale Kea-Mock prüft nun ebenfalls HTTP Basic Authentication.

## [0.1.1] - 2026-09-07

### Hinzugefügt

- Veröffentlichung eines signierten Multi-Arch-Container-Images über GHCR.
- SBOM und Build-Provenance für veröffentlichte Container-Images.

### Geändert

- Compose verwendet standardmäßig das öffentliche GHCR-Image; lokale Builds
  erfolgen über eine separate Override-Datei.

## [0.1.0] - 2026-09-07

### Hinzugefügt

- Read-only-Weboberfläche für aktive Kea-DHCPv4-Leases.
- Teiltreffersuche nach Hostname und normalisierter MAC-Adresse.
- Nach freigegebenen Subnetzen gruppierte und paginierte Listenansicht.
- Modularer DHCP-Provider und interne Gerätenamen-Resolver-Schnittstelle.
- Offline-Herstellerauflösung mit IEEE MA-L-, MA-M- und MA-S-Daten.
- 30-Sekunden-Snapshot mit begrenztem Stale-Fallback und manuellem Refresh.
- Deutsche und englische Oberfläche.
- Non-Root-Container, Compose-Konfiguration und lokaler Kea-Entwicklungsmock.
- GitHub-CI für Formatierung, Linting, Typprüfung, Tests, Security und Image-Build.

[Unreleased]: https://github.com/Phill93/LeaseLurker/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Phill93/LeaseLurker/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Phill93/LeaseLurker/releases/tag/v0.1.0
