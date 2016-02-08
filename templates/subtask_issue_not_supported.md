{% extends "message.md" %}

{% block title -%}
Cannot merge a subtask
{% endblock %}

{% block message %}
The Jira issue {{ issue.key }} is a subtask. I can only merge
the following issue types into development branches:

Jira issue type  |  corresponding branch prefix
-----------------|------------------
{% for pair in pairs -%}
`{{ pair }}` | `{{ pairs[pair] }}`
{% endfor %}

To fix this problem:

- create a branch for the parent issue {{ issue.fields.parent.key }} if it does not exist yet,
- change the destination branch of this pull request to the parent branch, merge your work (I will not be involved),
- create a new pull request for the parent branch when the work related to the parent issue is complete.
{% endblock %}
