This pull request has been created automatically by @{{ wall_e }}.
It is linked to its parent pull request #{{ pr['id'] }}.

**Do not edit this pull request directly.**

If you need to amend/cancel the changeset on branch
`{{ pr['source']['branch']['name'] }}`, please follow this
procedure:

```
#!bash
 $ git fetch
 $ git checkout {{ pr['source']['branch']['name'] }}
 $ # <amend or cancel the changeset by _adding_ new commits>
 $ git push
```

However, if you need to add changes for versions *posterior* to the initial
target version, you will have to modify the corresponding
`w/<target_version>/*` integration branch.

In any case, please always comment pull request #{{ pr['id'] }} instead of this
one.
