# TASK: sendObject - Purge Datastream

# handles
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import utilities
import WSUDOR_ContentTypes
import localConfig
from flask import Blueprint, render_template, request


sendObject = Blueprint('sendObject', __name__, template_folder='templates', static_folder="static")


@sendObject.route('/sendObject', methods=['POST', 'GET'])
@utilities.objects_needed
def index():

	return render_template("sendObject.html", REMOTE_REPOSITORIES=localConfig.REMOTE_REPOSITORIES)


def sendObject_worker(job_package):

	# open handle
	obj_handle = WSUDOR_ContentTypes.WSUDOR_Object(job_package['PID'])	

	# get params
	if 'refresh_remote' in job_package['form_data']:
		refresh_remote = True
	else:
		refresh_remote = False
	dest_repo = job_package['form_data']['dest_repo']

	# look for host rewrite
	if 'refresh_remote' in job_package['form_data']:
		host_rewrite = job_package['form_data']['host_rewrite']
	else:
		host_rewrite = False

	# send object with object method
	obj_handle.sendObject(dest_repo, refresh_remote=refresh_remote, host_rewrite=host_rewrite)
	