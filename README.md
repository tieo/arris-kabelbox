# arris-kabelbox

Deklarative Konfiguration von ARRIS/Vodafone Kabelbox-Routern per Selenium.

## Getestetes Gerät

| | |
|---|---|
| **Modell** | Vodafone Docsis 3.1 (ARRIS TG3442DE / Vodafone Station) |
| **Firmware** | `01.05.063.13.EURO.SIP` |
| **Plattform** | RDK-B `rdkb-2022q1-dunfell` |
| **UI-Sprache** | Deutsch |

Andere Firmware-Versionen oder Modelle der ARRIS 950-Familie funktionieren eventuell auch, wurden aber nicht getestet.

## Features

- **Statische DHCP-Reservierungen:** Anlegen, Löschen, Sync auf Soll-Zustand
- **Port-Forwarding:** Anlegen, Löschen, Sync (eine Regel pro Apply-Zyklus wegen Router-Limitierung)
- **WiFi:** SSID lesen/ändern, Status, MAC-Filter auslesen
- **Firewall:** Status lesen, ein-/ausschalten
- **DynDNS:** Konfiguration auslesen
- **Status:** Verbundene Geräte, Router-Info, Event-Log
- **Deklarativer Modus:** YAML-Datei beschreibt den Soll-Zustand, `kabelbox apply` gleicht ab

## Installation

```bash
uv tool install --python "<3.14" .
# oder
pip install .
```

> **Hinweis:** Pydantic unterstützt derzeit kein Python 3.14. Falls `python3.14` dein Standard-Interpreter ist, muss `--python "<3.14"` angegeben werden.

## Benutzung

```bash
# Passwort per Env-Variable oder --password Flag
export KABELBOX_PASSWORD=meinpasswort

# Geräte auflisten
kabelbox status
kabelbox dhcp list
kabelbox ports list

# WiFi / Firewall / DynDNS
kabelbox wifi status
kabelbox firewall status
kabelbox ddns

# Router-Info und Event-Log
kabelbox info
kabelbox log

# Deklarativ: Soll-Zustand anwenden
kabelbox apply config.yaml
kabelbox apply config.yaml --dry-run

# Router neustarten
kabelbox restart --yes
```

Siehe [`config.example.yaml`](config.example.yaml) für ein Beispiel.

## Robustheit

- **UI-Modus-unabhängig:** Navigiert per `mid`-Parameter, funktioniert im Standard- und Experten-Modus
- **Sprachunabhängig:** Selektoren nutzen nur Element-IDs, keine lokalisierten Strings
- **Automatischer Experten-Modus:** Wechselt nach dem Login automatisch
- **Retry mit Backoff:** Fehlgeschlagene Aktionen werden automatisch wiederholt
- **Screenshot bei Fehler:** Bei unerwarteten Fehlern wird ein Screenshot gespeichert

## Keine Gewähr

**Dieses Projekt wird ohne jegliche Gewährleistung bereitgestellt ("as is").**
Die Nutzung erfolgt auf eigene Gefahr. Für Schäden durch die Verwendung dieser Software wird keine Haftung übernommen, auch nicht für Konfigurationsänderungen am Router, Verbindungsabbrüche oder sonstige Netzwerkprobleme.

Kein Bezug zu ARRIS, CommScope oder Vodafone. Alle Marken gehören ihren jeweiligen Inhabern.

## AI Notice

Dieses Projekt wurde mithilfe von KI (Claude, Anthropic) entwickelt und gegen einen echten Router getestet.

## Lizenz

[MIT](LICENSE)
