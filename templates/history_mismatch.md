{% extends "message.md" %}

{% block title -%}
History mismatch
{% endblock %}

{% block message %}
Commit #{{commit}}, which belongs to the first integration branch
`{{integration_branch.name}}`, appears to come neither from
th development branch `{{development_branch.name}}`, nor from the
feature branch `{{feature_branch.name}}`.

Either the feature branch history has changed (e.g. a rebase),
or a commit was added directly on the first integration branch
`{{integration_branch.name}}`.

In either cases, the merge is not possible until all related `w/*`
branches are manually deleted or rebased.
{% endblock %}
