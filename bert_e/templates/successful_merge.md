{% extends "message.md" %}

{% block message %}
I have successfully merged the changeset of this pull request
into targetted development branches:

{% for branch in branches %}
* :heavy_check_mark: `{{ branch.name }}`
{% endfor %}

{% if ignored %}
The following branches have **NOT** changed:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}

{% if pending_hotfixes %}
This pull request did not target the following hotfix branch(es) so they
were left untouched:

{% for branch in pending_hotfixes -%}
* `{{ branch.name }}`
{% endfor %}
{% endif %}

Please check the status of the associated issue {{ issue }}.

Goodbye {{ author }}.
{% endblock %}
