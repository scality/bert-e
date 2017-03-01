{% extends "message.md" %}

{% block title -%}
Reset warning
{% endblock %}

{% block message %}
There are commits on integration branches that may be lost forever if you
choose to *reset* them.

Are you really sure to delete `{{integration_branch.name}}` since it appears
to contain manual changes?

**You can use the `force_reset` command if you still want me
to delete those branches.**

{% endblock %}
