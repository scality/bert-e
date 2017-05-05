{% extends "message.md" %}

{% block title -%}
Unsupported issue type
{% endblock %}

{% block message %}
The Jira issue {{ issue.key }} is of type {{ issue.fields.issuetype.name }} and cannot be used to reference a branch.

{% if pairs %}
I can only merge the following issue types into development branches:

Jira issue type  |  corresponding branch prefix
-----------------|------------------
{% for pair in pairs -%}
`{{ pair }}` | `{{ pairs[pair] }}`
{% endfor %}
{% endif %}

{% if issue.fields.issuetype == 'Sub-task' -%}
To fix this problem:

- create a branch for the parent issue {{ issue.fields.parent.key }} if it does not exist yet,
- change the destination branch of this pull request to the parent branch, merge your work (I will not be involved),
- create a new pull request for the parent branch when the work related to the parent issue is complete.
{%- endif %}
{% endblock %}
