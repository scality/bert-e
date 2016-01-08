This pull-request has been created automatically by @{{ WALL_E_USERNAME }}.
It is linked to its parent pull request #{{ pr['id'] }}
Please do not edit the contents nor the title!
The only actions allowed are "Approve" or "Comment".
You may want to refactor the branch `{{ pr['source']['branch']['name'] }}`
manually :
```
#!bash
 $ git checkout {{ pr['source']['branch']['name'] }}
 $ git pull
 $ # do interesting stuff\n'
 $ git add <modified_files>
 $ git commit
 $ git push
```
