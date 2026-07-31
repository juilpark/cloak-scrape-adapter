# Third-party notices

## CloakBrowser Python wrapper

This project depends on the `cloakbrowser` Python wrapper:

- Source: https://github.com/CloakHQ/CloakBrowser
- Copyright (c) 2026 CloakHQ
- License: MIT

The wrapper's MIT license permits dependency use and redistribution subject to
preserving its copyright and license notice. The installed Python distribution
also carries its own license metadata.

## CloakBrowser Chromium binary

The CloakBrowser Chromium binary is **not included** in this repository or its
public container image. On first runtime launch, the operator may download it
directly from an official CloakHQ distribution channel.

The binary is governed by a separate license:

https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md

That license includes restrictions on redistribution and separate terms for
OEM, SaaS, hosted browser, and third-party customer use. Operators are
responsible for reviewing and accepting those terms for their deployment.

## Playwright

The CloakBrowser wrapper depends on Microsoft Playwright.

- Source: https://github.com/microsoft/playwright-python
- License: Apache License 2.0

## Firecrawl compatibility notice

Firecrawl is only the compatibility target for the public `/health` and
`/scrape` HTTP contract. This repository contains no copied or translated
Firecrawl source code and is not affiliated with or endorsed by Firecrawl.
