## 1.0.3

- Fix Pack Voltage reading negative on high-voltage systems (e.g. 48V+ packs). The shunt voltage field was decoded as a signed integer, causing overflow above ~327V. Now correctly decoded as unsigned.

## 1.0.2

- Initial public release.
