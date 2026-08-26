# Contributing

Crab accepts focused changes that preserve its route, command, and data-access boundaries.

1. Branch from `main` and keep each pull request to one reviewable concern.
2. Add the smallest test that proves the changed behavior, especially for authentication, consent, identity, exports, studies, and rewards.
3. Build the test image and run the release suite from [the verification workflow](.github/workflows/hardened-candidate.yml).
4. Never commit credentials, participant data, private deployment details, generated receipts, or unlicensed media.

By submitting a contribution, you represent that you have the right to provide it and agree that it is licensed under GNU GPLv3, the same license as the project.
