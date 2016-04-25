{% extends "message.md" %}

{% block title -%}
Integration pull requests created
{% endblock %}

{% block message %}

The integration branches and associated pull requests have been created,
and now is a great time to review that the changesets match your expectations.
You may also cancel a changeset on a specific target version if required.

{% for pr in child_prs -%}
* child pull request #{{ pr['id'] }} will merge `{{ pr['source']['branch']['name'] }}`
 into `{{ pr['destination']['branch']['name'] }}`
{% endfor %}

{% if ignored %}
The following branches will **NOT** be impacted:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}

The method to update the changeset is described in each child pull request. I will
re-analyse this pull request automatically after changes are pushed to the central
repository.
{% endblock %}
