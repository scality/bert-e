{% extends "message.md" %}

{% block title -%}
In the queue
{% endblock %}

{% block message %}
The changeset has received all authorizations and has been added to the
relevant queue(s). The queue(s) will be merged in the target development
branch(es) as soon as builds have passed.

The changeset will be merged in:

{% for branch in branches %}
* :heavy_check_mark: `{{ branch.name }}`
{% endfor %}

{% if ignored %}
The following branches will **NOT** be impacted:

{% for branch_name in ignored -%}
* `{{ branch_name }}`
{% endfor %}
{% endif %}

There is no action required on your side. You will be notified here once
the changeset has been merged. In the unlikely event that the changeset
fails permanently on the queue, a member of the admin team will
contact you to help resolve the matter.

*IMPORTANT*

Please do not attempt to modify this pull request.

* Any commit you add on the source branch will trigger a new cycle after the
  current queue is merged.
* Any commit you add on one of the integration branches will be **lost**.

If you need this pull request to be removed from the queue, please contact a
member of the admin team now.
{% endblock %}
