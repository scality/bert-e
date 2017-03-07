{% extends "message.md" %}

{% block title -%}
Reset complete
{% endblock %}

{% block message %}
I have successfully deleted this pull request's integration branches.

{% if couldnt_decline -%}
**However, I couldn't decline the following integration pull requests:**

{% for pr in couldnt_decline %}
* {{ pr.id }}
{% endfor %}
You might need to decline them manually before I can proceed.
{%- endif %}
{% endblock %}
