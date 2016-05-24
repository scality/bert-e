from filter_pull_requests import filter_pr
import wall_e
import sys
import urllib
import requests

# This restores the same behavior as before.
USERNAME = ''
PASSWD = ''
EMAIL = ''
TEAM = 'scality'
WALL_E_PASSWORD=''
reload(sys)
sys.setdefaultencoding('utf-8')

p = filter_pr(USERNAME, PASSWD, EMAIL, TEAM,
              'ring', destination='', source='', author='^((?!Wall).)*$',
              close_source_branch='', state='OPEN', title='', created_on='',
              updated_on='')

def handle(pull_request_id):
    sys.argv = ["wall-e.py"]
    sys.argv.append('--settings')
    sys.argv.append('ring')
    sys.argv.append('--slug')
    sys.argv.append('ring')
    sys.argv.append('--reference-git-repo')
    sys.argv.append('/tmp/wall_e_stats/ring')
    sys.argv.append('--quiet')
    sys.argv.append('--dry-run')
    sys.argv.append(str(pull_request_id))
    sys.argv.append(WALL_E_PASSWORD)
    return wall_e.main()

#p = {2743: {'author': 'author', 'source':'from', 'destination':'to', 'created_on':'', 'updated_on': ''}}
for (pr_id, data) in p.items():
    code, excp, repeat = handle(pr_id)
    print('{}; {}; {}; {}; {}; {}; {}; {}; {}'.format(
        pr_id,
        code,
        excp,
        repeat,
        data['author'],
        data['source'],
        data['destination'],
        data['created_on'],
        data['updated_on']))
