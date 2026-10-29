# Security Policy

## Supported versions

Security fixes go into the latest release. If you're on an older version, update through HACS first and check whether the problem is still there.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use GitHub's private reporting instead: open the [Security tab](https://github.com/hiall-fyi/atmos_ce/security) of this repository and choose **Report a vulnerability**. Only the maintainer can see what you send there.

A useful report says which weather source is involved, what you expected, and what happened instead, with a debug log if you have one. Remove your latitude and longitude from the log before you attach it.

You'll get a reply once the report has been read. Once a fix is ready it goes into a release, and that release's CHANGELOG entry says what was fixed.

## What's in scope

Atmos CE sends requests to public weather services and, for CWA Taiwan, uses an API key you enter. These are the kinds of thing worth reporting:

- Your home location or an API key showing up in a log, an error message, a diagnostics download or an entity attribute
- A weather service's reply causing the integration to run code it shouldn't, or to crash Home Assistant
- A way for a response from one of the services to read or write anything outside the integration's own data
