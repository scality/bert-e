Please approve this pull request (reviewers and author), if you think
that the integration pull requests are **ready to be merged**.

Before approving, you should double check the diffs of the integration
pull requests to ensure that the changesets I'm about to merge into the
development branches are correct:

* this pull request #{{ pr['id'] }}
will merge `{{ pr['source']['branch']['name'] }}`
into `{{ pr['destination']['branch']['name'] }}`
{% for pr in child_prs -%}
 * pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}
If you think that one of the auto-generated changesets is not ok, you can
modify the `w/*` integration branches accordingly.

For example, if you don't want this changeset to land in
`{{ child_prs[0]['destination']['branch']['name'] }}`:

```
#!bash
 $ git fetch
 $ git checkout {{ child_prs[0]['source']['branch']['name'] }}
 $ git log --oneline # to have the <sha1> of the commit(s) you need to revert
 $ git revert <sha1>
 $ git push
```
I will then relaunch the checks with your new changesets and try to merge.
