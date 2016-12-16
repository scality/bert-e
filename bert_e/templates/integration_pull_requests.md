{% extends "message.md" %}

{% block title -%}
Integration pull requests created
{% endblock %}

{% block message %}
I have created the following integration pull requests:

{% for pr in child_prs -%}
* integration pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}

Now would be a great time to *follow* them if you would like to be notified of
build statuses by email.

{% if ignored %}
The following branches will **NOT** be impacted:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}
{% endblock %}
