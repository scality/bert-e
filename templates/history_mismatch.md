{% extends "message.md" %}

{% block title -%}
History mismatch
{% endblock %}

{% block message %}
Commit #{{commit}}, on the first integration branch
`{{integration_branch.name}}`, appears to come neither from
the development branch `{{development_branch.name}}`, nor from the
source branch `{{feature_branch.name}}`.

Either the source branch history has changed (e.g. a rebase),
or a commit was added directly on the first integration branch
`{{integration_branch.name}}`.

In either cases, the merge is not possible until all related `w/*`
branches are manually deleted or updated. Once fixed, please comment
this pull request to resume the merge process.
{% endblock %}
