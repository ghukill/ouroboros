print "importing WSUDOR_Manager"
from WSUDOR_Manager import *
from WSUDOR_Manager import jobs

# python
import os

print "importing fedora handles"
fedora_handle = fedoraHandles.fedora_handle
from WSUDOR_Manager import fedoraHandles

print "importing solr handles"
solr_handle = solrHandles.solr_handle
solr_bookreader_handle = solrHandles.solr_bookreader_handle

print "creating WSUDOR shortcuts"
w = WSUDOR_ContentTypes.WSUDOR_Object

print "importing eulfedora"
import eulfedora

print "creating MySQL shortcut - `m()` with root password"
def my():
	return os.system('mysql -u root -p WSUDOR_Manager')

print "creating bash shortcut - 'bash'"
def bash():
	return os.system('bash')

# DEBUG
def tableWipe():
	try:
		db.session.execute('DROP TABLE ingest_workspace_object;')
		print "ingest_workspace_object dropped."
	except:
		print "ingest_workspace_object not found..."
	try:
		db.session.execute('DROP TABLE ingest_workspace_job;')
		print "ingest_workspace_job dropped."
	except:
		print "ingest_workspace_job not found..."
	try:
		db.session.execute('DROP TABLE user;')
		print "user dropped."
	except:
		print "user not found..."
	print "commiting..."
	db.session.commit()

	print "recreating..."
	db.create_all()

# logs
def tailUserCelery(user):
	os.system("tail -f /var/log/celery-%s.err.log" % user)


# function to grab single object from remote repository
def getRemoteObject(repo, PID, index=True, skip_constituents=False):
	
	sync_list = [PID]
	
	# remote repo
	dest_repo_handle = fedoraHandles.remoteRepo(repo)
	
	# check if remote object has constituent parts
	if not skip_constituents:
		constituents = dest_repo_handle.risearch.spo_search(None,"fedora-rels-ext:isConstituentOf","info:fedora/%s" % PID)
		print len(constituents)
		if len(constituents) > 0:
			for constituent in constituents:
				# add to sync list
				print "adding %s to sync list" % constituent[0]
				sync_list.append(constituent[0])
			
	# sync objects 
	for i,pid in enumerate(sync_list):
		print "retrieving %s, %d/%d..." % (pid,i,len(sync_list))
		print eulfedora.syncutil.sync_object(dest_repo_handle.get_object(pid), fedora_handle, show_progress=False, export_context='archive')
	
	
# function to clone object datastream by datastream
def cloneRemoteObject(repo, PID):
	pass
	

def getIngestWorkspaceRows(job_num):
	iwjob = models.ingest_workspace_job.query.filter_by(id=job_num).first()
	iwrows = models.ingest_workspace_object.query.filter_by(job=iwjob)
	print "returning tuple of (job_handle, job_rows)"
	return (iwjob,iwrows)
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	
	


