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
  the pull request from the queue for further analysis and maybe rebase/merge.

<details>
  <summary><b>Remove the pull request from the queue</b></summary>

- Add a `/wait` comment on this pull request.
- Click on login on the [status page]({{ frontend_url }}).
- Go into the [manage]({{ frontend_url }}/manage) page.
- Find the option called `Rebuild the queue` and click on it.
  Bert-E will loop again on all pull requests to put the valid ones
  in the queue again, while skipping the one with the `/wait` comment.
- Wait for the new queue to merge, then merge/rebase your pull request
  with the latest changes to then work on a proper fix.
- Once the issue is fixed, delete the `/wait` comment and
  follow the usual process to merge the pull request.

</details>


{% endblock %}
