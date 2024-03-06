{% extends "message.md" %}

{% block title -%}
Queue build failed
{% endblock %}

{% block message %}

The corresponding build for the queue failed:

- Checkout the [status page]({{ frontend_url }}).
- Identify the failing build and review the logs.
- If no issue is found, re-run the build.
- If an issue is identified, checkout the steps below to remove
  the pull request from the queue.

<details>
  <summary><b>Remove the pull request from the queue</b></summary>

- Add a `/wait` comment on the pull request.
- Click on login on the [status page]({{ frontend_url }})
- Go into the [manage]({{ frontend_url }}/manage) page.
- Find the option called `Rebuild the queue` and click on it.
  This will remove the pull request from the queue.
- Wait for the new queue to merge, then update your pull request
  with the latest change to then work on a proper fix.
- Once the issue is fixed, delete the `/wait` comment and
  follow the usual process to merge the pull request.

</details>


{% endblock %}
