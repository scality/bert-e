{% extends "message.md" %}

{% block title -%}
Fixup commits detected
{% endblock %}

{% block message %}
The following commits on branch `{{ src_branch }}` appear to be intended for
interactive rebase and must be squashed before merging:

{% for commit in fixup_commits %}
- `{{ commit.sha1[:12] }}` {{ commit.message }}
{% endfor %}

Please squash these commits using `git rebase -i` and force-push the result
to your branch.
{% endblock %}
