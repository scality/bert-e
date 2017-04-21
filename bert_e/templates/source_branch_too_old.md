{% extends "message.md" %}

{% block title -%}
Branches have diverged
{% endblock %}

{% block message %}
This pull request's source branch `{{ src_branch }}` has diverged from
`{{ dst_branch }}` by more than {{ threshold }} commits.

To avoid any integration risks, please re-synchronize them using one of the
following solutions:

* Merge `origin/{{ dst_branch }}` into `{{ src_branch }}`
* Rebase `{{ src_branch }}` onto `origin/{{ dst_branch }}`

Note: If you choose to rebase, you may have to ask me to rebuild
integration branches using the `reset` command.
{% endblock %}
