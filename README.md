# Crab

Crab is the DataUnion backend. It accepts wallet-authenticated contributions, keeps consent and ownership decisions server-side, and supports governed studies, privacy-limited exports, and reward claims.

This repository contains the DataUnion backend and its historical domain integrations. Separately maintained Brainstem Health client repositories are not part of this release.

The public history begins with a reviewed release cut because the private development repository also contained excluded operational material and third-party fixtures. The code predates that import and was developed by DataUnion contributors over multiple years.

## Design boundaries

HTTP routes translate requests into commands. Commands own validation and business decisions. Data-access objects isolate CouchDB access. New behavior should preserve those boundaries instead of putting policy in routes or database helpers.

The backend treats participant data and rewards as trust boundaries:

- unknown or withdrawn consent fails closed;
- identity-bearing records stay server-side unless an explicit export contract permits a privacy-limited projection;
- study releases bind approval to immutable versions and digests;
- reward retries require an unambiguous chain result;
- retired administrative and bulk-export routes remain unavailable.

See [SECURITY.md](SECURITY.md) before deploying or reporting a vulnerability.

## Build and verify

The supported test environment is the pinned Python 3.11 Docker image and locked production dependencies:

```bash
docker build --target test -t crab-test .
```

The release suite is defined in [the verification workflow](.github/workflows/hardened-candidate.yml). Runtime configuration starts from [sample.ini](sample.ini); never commit a populated `properties.ini`.

Marine provides the hardened Compose and migration boundary for deployment. Its guides cover immutable images, private service networking, backup and restore proof, canaries, and rollback.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Changes to consent, identity, exports, authentication, studies, or rewards require focused tests for the affected trust boundary.

## License

Crab is distributed under the GNU General Public License, version 3. See [LICENSE](LICENSE).
