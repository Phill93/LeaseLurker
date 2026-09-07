# ADR 0001: Read-only adapter architecture

- Status: Accepted
- Date: 2026-09-07

## Context

LeaseLurker must query Kea today without coupling its search and presentation logic
to Kea forever. It must never mutate DHCP state.

## Decision

Domain services depend on `DhcpLeaseProvider`, which exposes only capability checks,
subnet reads, lease reads, and health. `KeaProvider` additionally enforces a command
allowlist. Device-name enrichment follows a separate internal
`DeviceNameResolver` interface. There is no dynamic third-party plugin loading in
version 1.

## Consequences

Another DHCP implementation can be introduced without changing the UI or search
logic. A write operation cannot accidentally pass through the provider contract or
the Kea command transport.
