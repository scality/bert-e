Hi @{{ wall_e.original_pr['author']['username'] }} and `reviewers`,
you 'll need to approve this pull request if you think that it is
**ready to be merged**.

{% if wall_e.child_prs|length > 0 %}
Before approving, you should double check the diffs of the auto-generated
pull requests to ensure that the changesets I'm about to merge into the
development branches are correct :

* this pull request #{{ wall_e.original_pr['id'] }}
will merge `{{ wall_e.original_pr['source']['branch']['name'] }}`
into `{{ wall_e.original_pr['destination']['branch']['name'] }}`
{% for pr in wall_e.child_prs -%}
 * pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}
If you think that one of the auto-generated changesets is not ok, you can
modify the `w/*` integration branches accordingly.

For example, if you don't want this changeset to land in
`{{ wall_e.child_prs[0]['destination']['branch']['name'] }}`,
you'll need to :

```
#!bash
 $ git fetch
 $ git checkout {{ wall_e.child_prs[0]['source']['branch']['name'] }}
 $ git log --oneline # to have the <sha1> of the commit(s) you need to revert
 $ git revert <sha1>
 $ git push
```
I'll then relaunch the checks with your new changesets and try to merge.
{% endif %}