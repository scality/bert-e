{% extends "message.md" %}

{% block title -%}
Incompatible branch type
{% endblock %}

{% block message %}
I cannot merge the branch `{{ source.name }}` into
`{{ destination.name }}`.
The only prefixes accepted in this branch are:

{% for prefix in destination.allow_prefix %}
* `{{ prefix }}/`
{% endfor %}

Please rename the source branch and create a new pull request.
{% endblock %}
