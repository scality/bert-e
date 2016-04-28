{% extends "message.md" %}

{% block title -%}
Integration pull requests created
{% endblock %}

{% block message %}
The following integration branches and associated pull requests have been created:

{% for pr in child_prs -%}
* pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}

{% if ignored %}
The following branches will **NOT** be impacted:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}
{% endblock %}
