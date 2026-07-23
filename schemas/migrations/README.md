# Schema migrations

Migrations are explicit transformations that read a validated source artifact and create a new artifact
under the destination schema. They must record source/destination hashes and superseding relationships.
No migration may rewrite historical source artifacts in place.

