from filter_pull_requests import filter_pr
import wall_e
import sys
import urllib
import requests

# This restores the same behavior as before.
JENKINS_URI = "buildmaster.devsca.com:8081"
JENKINS_USER = "releng"
JENKINS_JOB = "WALL_E"
USERNAME = "releng"
JENKINS_AUTH_TOKEN = 'e3841b46abc34d2d82762899d93e7317'
JENKINS_JOB_TOKEN = 'LVa8rRtBsqo_w6tA'
count = 0
pr_ids = [517, 518, 519, 531, 532, 533, 563, 569, 578, 593, 597, 598, 622, 623,
645, 646, 651, 655, 670, 673, 674, 700, 798, 331, 880]
reload(sys)
sys.setdefaultencoding('utf-8')

p = filter_pr('mvaude', '***REMOVED***', 'maxime.vaude@scality.com', 'scality',
              'ring', destination='development/*', source='', author='^((?!Wall).)*$',
              close_source_branch='', state='', title='', created_on='',
              updated_on='')

def launch_job(pr_id):
    """
    Launch Wall-E Job from Jenkins
    """
    params = urllib.urlencode({'token': JENKINS_JOB_TOKEN,
                               'REPOSITORY_OWNER': 'scality',
                               'REPOSITORY_SLUG': 'ring',
                               'PULL_REQUEST_ID': pr_id})
    url = "https://%s:%s@%s/job/%s/buildWithParameters?%s" % (
        JENKINS_USER,
        JENKINS_AUTH_TOKEN,
        JENKINS_URI,
        JENKINS_JOB,
        params)
    # verify=false: bypass SSL certificate verification
    resp = requests.post(url, {}, allow_redirects=True, verify=False)
    assert(resp.status_code == requests.codes.created)


#for (pr_id, pr_log) in p.items():
for pr_id in pr_ids:
    pr_log = ""
#    if count > 10:
#        break
#    print('{}/{}; {}; {}'.format(count, len(p.items()) pr_id, pr_log))
    print('{}/{}; {}; {}'.format(count, len(pr_ids), pr_id, pr_log))
    launch_job(pr_id)
    count += 1
