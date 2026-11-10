# Published-video registry

The publishing stage will maintain `videos.json`, with one record per confirmed upload: channel ID, idea ID, content hash, YouTube video ID, visibility, and publication timestamp.

Reject an upload when its idea ID or content hash already exists for that channel. If an upload times out, reconcile against YouTube before retrying; never blindly upload again.
