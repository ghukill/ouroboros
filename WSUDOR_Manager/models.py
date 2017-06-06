from flask.ext.login import UserMixin
from flask import session
from datetime import datetime
import sqlalchemy
from json import JSONEncoder
from flask import Response, jsonify
import fileinput
import xmlrpclib
import os
from lxml import etree
import re
import eulfedora
import json
import requests

# eulxml, used for PREMISClient
from eulxml.xmlmap import premis

from WSUDOR_Manager import db, actions, app
from WSUDOR_Manager.solrHandles import solr_handle
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import CeleryWorker
from WSUDOR_Manager import logging

# import derivatives
from inc.derivatives import Derivative

# pypremis
from pypremis.lib import PremisRecord
import pypremis

# session data secret key
####################################
app.secret_key = 'WSUDOR'
####################################


########################################################################
# User Jobs
########################################################################

class user_pids(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	PID = db.Column(db.String(255))
	username = db.Column(db.String(255))
	status = db.Column(db.Boolean(1))
	group_name = db.Column(db.String(255))
	notes = db.Column(db.String(4096))

	def __init__(self, PID, username, status, group_name, notes=None):
		self.PID = PID
		self.username = username
		self.status = status
		self.group_name = group_name
		self.notes = notes

	def __repr__(self):
		return '<PID %s, username %s>' % (self.PID, self.username)


class user_jobs(db.Model):
	job_num = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=False)
	username = db.Column(db.String(255))
	# for status, expecting: spooling, pending, running, completed, supressed
	status = db.Column(db.String(255))
	celery_task_id = db.Column(db.String(255))
	job_name = db.Column(db.String(255))

	def __init__(self, job_num, username, celery_task_id, status, job_name):
		self.job_num = job_num
		self.username = username
		self.celery_task_id = celery_task_id
		self.status = status
		self.job_name = job_name

	def __repr__(self):
		return '<Job# %s, username: %s, celery_task_id: %s, status: %s>' % (self.job_num, self.username, self.celery_task_id, self.status)

#Login_serializer used to encryt and decrypt the cookie token for the remember
#me option of flask-login
# login_serializer = URLSafeTimedSerializer(app.secret_key)

class User(db.Model, UserMixin):
	
	id = db.Column('id', db.Integer, primary_key=True)
	username = db.Column('username', db.String(64), index=True, unique=True)
	role = db.Column('role', db.String(120), nullable=True)
	displayName = db.Column('displayName', db.String(120), nullable=False)

	def __init__(self, username, role, displayName):
		self.username = username
		# parse roles
		if type(role) == list:
			self.role = ','.join(role)
		elif type(role) == str:    
			self.role = role
		self.displayName = displayName

	def get_auth_token(self):
		"""
		Encode a secure token for cookie
		"""
		data = [str(self.id), self.fedoraRole]
		return login_serializer.dumps(data)
 
	@staticmethod
	def get(user):
		"""
		Static method to search the database and see if userid exists.  If it 
		does exist then return a User Object.  If not then return None as 
		required by Flask-Login. 
		"""
		for user in User.query.session.query(User).filter_by(username=user):
			return user
		return None

	# return roles as list
	def roles(self):
		return [role.strip() for role in self.role.split(',')]

	def is_authenticated(self):
		return True

	def is_active(self):
		return True

	def is_anonymous(self):
		return False

	def get_id(self):
		return unicode(self.id)

	def __repr__(self):
		return '<User %r>' % (self.username)


class job_rollback(db.Model):
	job_num = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=False)
	username = db.Column(db.String(255))
	taskname = db.Column(db.String(255))
	rollback_content = db.Column(db.String(10000))
	

	def __init__(self, job_num, username, taskname, rollback_content):
		self.job_num = job_num
		self.username = username
		self.taskname = taskname
		self.rollback_content = rollback_content
		

	def __repr__(self):     
		return '<Job# %s, username: %s>' % (self.job_num, self.username)


class xsl_transformations(db.Model):
	id = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=True)   
	name = db.Column(db.String(255))
	description = db.Column(db.String(1000))
	xsl_content = db.Column(db.Text(4294967295), nullable=False) #must be Text(4294967295) to work  

	def __init__(self, name, description, xsl_content):     
		self.name = name
		self.description = description
		self.xsl_content = xsl_content
		

	def __repr__(self):     
		return '<Name: %s, Description: %s>' % (self.name, self.description)


class ingest_MODS(db.Model):
	id = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=True)   
	name = db.Column(db.String(255))
	created = db.Column(db.DateTime, default=datetime.now)
	xsl_transform_key = db.Column(db.Integer) # id of xsl_transform, might come in handy... 
	MODS_content = db.Column(db.Text(4294967295), nullable=False) #must be Text(4294967295) to work 

	def __init__(self, name, xsl_transform_key, MODS_content):      
		self.name = name
		self.xsl_transform_key = xsl_transform_key
		self.MODS_content = MODS_content
		

	def __repr__(self):     
		return '<Name: %s>, ID: %s>' % (self.name, self.id)


########################################################################
# DB Classes for ingestWorkspace
########################################################################
class ingest_workspace_job(db.Model):
	id = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=True)   
	# human readable name for job
	name = db.Column(db.String(255)) 
	# identifier, points to collection
	collection_identifier = db.Column(db.String(255))
	created = db.Column(db.DateTime, default=datetime.now)
	# column for raw ingest metadata
	ingest_metadata = db.Column(db.Text(4294967295))
	# column to hold python code (Classes) for creating bags
	bag_creation_class = db.Column(db.String(4096))
	# file index 
	file_index = db.Column(db.Text(4294967295))
	# enrichment metadata for AEM
	enrichment_metadata = db.Column(db.Text(4294967295))

	def __init__(self, name):       
		self.name = name    

	def __repr__(self):     
		return '<Name: %s>, ID: %s>' % (self.name, self.id)

	def _delete(self):
		db.session.delete(self)
		db.session.commit()

	def _commit(self):
		db.session.add(self)
		db.session.commit()


def dump_datetime(value):
	"""Deserialize datetime object into string form for JSON processing."""
	if value is None:
		return None
	return [value.strftime("%Y-%m-%d"), value.strftime("%H:%M:%S")]


class ingest_workspace_object(db.Model):
	
	id = db.Column(db.Integer, primary_key=True, unique=True, autoincrement=True)
	ingest_id = db.Column(db.Integer)
	created = db.Column(db.DateTime, default=datetime.now)
	# lazy link to job table above
	job_id = db.Column(db.Integer, db.ForeignKey('ingest_workspace_job.id'))
	job = db.relationship('ingest_workspace_job', backref=db.backref('objects', lazy='dynamic'))
	# content fields
	MODS = db.Column(db.Text(4294967295)) 
	objMeta = db.Column(db.Text(4294967295))
	bag_binary = db.Column(db.Text(4294967295)) 
	bag_path = db.Column(db.String(4096))
	# derived metadata
	object_title = db.Column(db.String(4096))
	DMDID = db.Column(db.String(4096))
	AMDID = db.Column(db.String(4096))
	premis_events = db.Column(db.Text(4294967295))
	file_id = db.Column(db.String(255))
	ASpaceID = db.Column(db.String(255))
	struct_map = db.Column(db.Text(4294967295))
	pid = db.Column(db.String(255))
	# flags and status
	object_type = db.Column(db.String(255))
	ingested = db.Column(db.String(255))
	repository = db.Column(db.String(255)) # eventually pull from localConfig.REPOSITORIES
	bag_validation_dict = db.Column(db.Text(4294967295))
	aem_enriched = db.Column(db.String(255))

	# init with 'job' as ingest_workspace_job instance
	def __init__(self, job, object_title="Unknown", DMDID=None):        
		self.job = job
		self.object_title = object_title
		self.DMDID = DMDID
		self.AMDID = None
		self.file_id = None
		self.ASpaceID = None
		self.ingested = False
		self.repository = None
		self.aem_enriched = False

	def __repr__(self):     
		return '<ID: %s, OBJECT TITLE: %s>' % (self.id,self.object_title)

	def serialize(self):
		return {
			'id':self.id,
			'created':dump_datetime(self.created),
			'job':(self.job.name,self.job.id),
			'MODS':self.MODS,
			'objMeta':self.objMeta,
			'object_title':self.object_title,
			'DMDID':self.DMDID,
			'AMDID':self.AMDID,
			'file_id':self.file_id,
			'ASpaceID':self.ASpaceID,
			'ingested':self.ingested,
			'repository':self.repository,
			'struct_map':self.struct_map,
			'aem_enriched':self.aem_enriched
		}

	def _delete(self):
		db.session.delete(self) 
		db.session.commit()     

	def _commit(self):
		db.session.add(self)
		db.session.commit()
	

########################################################################
# objMeta class Object
########################################################################
class ObjMeta:
	# requires JSONEncoder

	def __init__(self, **obj_dict): 
			
		# required attributes
		self.id = "Object ID"
		self.policy = "info:fedora/wayne:WSUDORSecurity-permit-apia-unrestricted"
		self.content_type = "ContentTypes" #WSUDOR_X, not CM:X
		self.isRepresentedBy = "Datastream ID that represents object"
		self.object_relationships = []
		self.datastreams = []

		# optional attributes
		self.label = "Object label"

		# if pre-existing objMeta exists, override defaults
		self.__dict__.update(obj_dict)

	
	# function to validate ObjMeta instance as WSUDOR compliant
	def validate(self):
		pass

	def writeToFile(self,destination):
		fhand = open(destination,'w')
		fhand.write(self.toJSON())
		fhand.close()

	def importFromFile(self):
		pass

	def downloadFile(self,form_data):
		form_data = str(form_data)
		return Response(form_data, mimetype="application/json", headers={"Content-Disposition" : "attachment; filename=objMeta.json"})

	def writeToObject(self):
		pass

	def importFromObject(self):
		pass

		#uses jsonify to set Content-Type headers to application/json
	def displayJSONWeb(self):
		return jsonify(**self.__dict__)

	#uses JSONEncoder class, exports only attributes
	def toJSON(self):
		return JSONEncoder().encode(self.__dict__)


########################################################################
# Solr
########################################################################
class SolrFields(object):
		def __init__(self, **fields): 
			self.__dict__.update(fields)


class SolrDoc(object):  

	# init
	def __init__(self,id):
		self.id = id
		self.escaped_id = self.id.replace(":","\:")

		# get stateful, current Solr doc
		query_params = {
			"q":'id:%s' % (self.escaped_id),
			"rows":1
		}
		response = solr_handle.search(**query_params)
		if len(response.documents) > 0:
			self.doc = SolrFields(**response.documents[0])
			#store version, remove from doc
			self.version = self.doc._version_ 
			del self.doc._version_
			# finally, set exists to True
			self.exists = True
		else:
			self.doc = SolrFields()
			self.doc.id = self.id # automatically set ID as PID
			self.exists = False


	# delete doc in Solr
	def delete(self):
		delete_response = solr_handle.delete_by_key(self.id, commit=False)
		return delete_response


	# update doc to Solr
	def update(self):
		update_response = solr_handle.update([self.doc.__dict__], commit=False)
		return update_response


	def commit(self):
		return solr_handle.commit()


	def asDictionary(self):
		return self.doc.__dict__


class SolrSearchDoc(object):    

	# init
	def __init__(self,id):
		self.id = id
		self.escaped_id = self.id.replace(":","\:")

		# get stateful, current Solr doc
		query_params = {
			"q":'id:%s' % (self.escaped_id),
			"rows":1
		}
		response = solr_handle.search(**query_params)
		if len(response.documents) > 0:
			self.doc = SolrFields(**response.documents[0])
			#store version, remove from doc
			self.version = self.doc._version_
			del self.doc._version_
			# finally, set exists to True
			self.exists = True
		else:
			self.doc = SolrFields()
			self.doc.id = self.id # automatically set ID as PID
			self.exists = False


	def asDictionary(self):
		return self.doc.__dict__



# class for Generic Supervisor creation
class createSupervisorProcess(object):

	sup_server = xmlrpclib.Server('http://127.0.0.1:9001')

	def __init__(self,supervisor_name,supervisor_process,group=False,restartGroup=False):
		logging.debug("instantiating self")
		self.supervisor_name = supervisor_name
		self.path = '/etc/supervisor/conf.d/'
		self.filename = self.path+supervisor_name+".conf"
		self.supervisor_process = supervisor_process
		self.group = group
		self.restartGroup = restartGroup

	def _writeConfFile(self):
		logging.debug("adding conf file")
		# fire the supervisor worker process
		supervisor_process = self.supervisor_process

		if not os.path.exists(self.filename):
			with open(self.filename ,'w') as fhand:
				fhand.write(supervisor_process)
			return self.filename
		else:
			logging.debug("Conf files exists, skipping")
			return False


	def _removeConfFile(self):
		logging.debug("remove conf file")
		if os.path.exists(self.filename):
			# remove conf file
			return os.remove(self.filename)
		else:
			logging.debug("could not find conf file, skipping")
			return False


	def _startSupervisorProcess(self):
		logging.debug("adding process to supervisor")
		try:
			self.sup_server.supervisor.reloadConfig()
			self.sup_server.supervisor.addProcessGroup(self.supervisor_name)
		except:
			return False


	def _stopSupervisorProcess(self):
		logging.debug("stopping proccess from supervisor")
		try:
			self.sup_server.supervisor.stopProcess(self.supervisor_name)
			self.sup_server.supervisor.removeProcessGroup(self.supervisor_name)
		except:
			return False


	def _removeSupervisorProcess(self):
		logging.debug("manually removing proccess from supervisor")
		try:
			self.sup_server.supervisor.removeProcessGroup(self.supervisor_name)
		except:
			return False

	def _setGroup(self, group):
		logging.debug("setting group")
		try:
			if not group:
				# Set group to its default value
				group = (item for item in self.sup_server.supervisor.getAllProcessInfo() if item['name'] == self.supervisor_name).next()
				group = group['group']
			else:
				# Store this specific group into the current session
				session[group] = []
				session[group].append(self.supervisor_name)
				logging.debug("%s" % session[group])
			self.group = group
		except:
			return False

	def _removeFromGroup(self):
		try:
			session[self.group].pop(self.supervisor_name)
		except:
			logging.debug("Process not found in group")


	def _restartGroup(self):
		logging.debug("restarting process group")
		for each in session[self.group]:
			self.sup_server.supervisor.stopProcessGroup(each)
			self.sup_server.supervisor.startProcessGroup(each)


	def start(self):
		self._setGroup(self.group)
		self._writeConfFile()
		self._startSupervisorProcess()


	def restart(self):
		if self.restartGroup:
			self._restartGroup()
		else:
			self.stop()
			self.start()


	def stop(self):
		# self._removeFromGroup()
		self._removeConfFile()
		stop_result = self._stopSupervisorProcess()
		if stop_result == False:
			self._removeSupervisorProcess()



########################################################################
# PREMIS
########################################################################
class PREMISClient(object):

	'''
	This client will be used to initialize and add PREMIS 
	events to a PREMIS datastream.

	Initialize empty, or with PID (assuming 'PREMIS' ds_id)

	example PREMIS events from METS:
	https://gist.github.com/ghukill/844f218bd95afef60c51ba19058e5c38

	Some helpful readings:

	PREMIS and PROV-O in FC4:
		https://wiki.duraspace.org/display/FF/Design+-+PREMIS+Event+Service

	PROV-O and PREMIS merging:
		http://dcpapers.dublincore.org/pubs/article/view/3709

	Using 'wsudor' branch of fork of pypremis:
		https://github.com/WSULib/uchicagoldr-premiswork/tree/wsudor
	'''

	def __init__(self, pid=False, ds_id='PREMIS'):

		self.pid = pid
		self.ohandle = False
		self.premis_ds = False
		self.premis = False
		self.tempfile = None
		self.object_identifiers = []

		# if pid provided, attempt to retrieve PREMIS
		if pid:
			self.ohandle = fedora_handle.get_object(pid)
			if ds_id in self.ohandle.ds_list:
				self.premis_ds = self.ohandle.getDatastreamObject(ds_id)
				# write temp file
				self.tempfile = Derivative.write_temp_file(self.premis_ds)
				# load with pypremis
				self.premis = PremisRecord(frompath=self.tempfile.name)

			else:
				logging.debug("%s datastream not found, initializing PREMIS datastream" % ds_id)
				# gen object identifier
				object_identifier = pypremis.nodes.ObjectIdentifier('pid', pid)
				# set format type for object
				format_designation = pypremis.nodes.FormatDesignation(formatName='wsudor object')
				format = pypremis.nodes.Format(formatDesignation=format_designation)
				# add format to object_characteristics
				object_characteristics = pypremis.nodes.ObjectCharacteristics(format=format)
				# create object node
				o = pypremis.nodes.Object(object_identifier, "intellectual entity", object_characteristics)
				# add to premis record
				self.premis = PremisRecord(objects=[o])
				# write to datastream with .update()
				self.update()

		else:
			raise Exception("a pid is required to initialize a PREMISClient instance")


	def get_object_identifiers(self):
		for o in self.premis.get_object_list():
			o_id = o.get_objectIdentifier()[0]
			self.object_identifiers.append( (o.get_objectCategory(), o_id.get_objectIdentifierType(), o_id.get_objectIdentifierValue()) )
		return self.object_identifiers


	def update(self):

		# update
		if self.premis_ds:
			self.premis_ds.content = self.premis.to_xml()
			return self.premis_ds.save()

		# init and save
		else:
			self.premis_ds = eulfedora.models.FileDatastreamObject(self.ohandle, "PREMIS", "PREMIS", mimetype="text/xml", control_group='M')
			self.premis_ds.label = "PREMIS"
			self.premis_ds.content = self.premis.to_xml()
			return self.premis_ds.save()


	def serialize(self):
		
		# return using pypremis .to_xml() method
		return self.premis.to_xml()


	def add_jms_event(self, msg):

		# debug
		logging.info("############ DEBUG ############")
		logging.info("%s" % msg.body)
		logging.info("############ DEBUG ############")

		# if datastream worked on, determine if in PREMIS record?



		# prepare detail message
		eventDetail = "Fedora Commons Java Messaging Service (JMS); action %s, pid %s".encode('utf-8') % ( msg.methodName.encode('utf-8'), msg.pid.encode('utf-8') )
		eventDetail = json.dumps(msg.parsed_body)

		# parse jms event, expecting instance of FedoraJMSWorker from WSUDOR_Indexer
		event_dict = {
			'id':pypremis.nodes.EventIdentifier('urn', msg.parsed_body['entry']['id'].encode('utf=8')),
			'type':msg.parsed_body['entry']['title']['#text'].encode('utf=8'),
			'date':msg.parsed_body['entry']['updated'].encode('utf=8'),			
			'detail':pypremis.nodes.EventDetailInformation(eventDetail=eventDetail),
			'loi':pypremis.nodes.LinkingObjectIdentifier('pid', msg.pid.encode('utf-8'), 'intellectual entity')
		}

		# set as event
		'''
		self,
        eventIdentifier,
        eventType,
        eventDateTime,
        eventDetailInformation=None,
        eventOutcomeInformation=None,
        linkingAgentIdentifier=None,
        linkingObjectIdentifier=None
		event = pypremis.nodes.Event()
		'''
		event = pypremis.nodes.Event(
				event_dict['id'],
				event_dict['type'],
				event_dict['date'],
				eventDetailInformation=event_dict['detail'],
				linkingObjectIdentifier=event_dict['loi']
			)

		# add event to premis record
		self.premis.add_event(event)

		# update
		self.update()



########################################################################
# Archival Hierarchy
########################################################################

class ObjHierarchy(object):

	'''
	This class uses Mulgara's native ITQL search syntax as it is much faster.
	Possible to switch to SPARQL if necessary.

	NOTE: currently this only works when objects have only one `hasParent`
	'''


	def __init__(self, pid=None, title=None, is_root=False):
		self.pid = pid
		self.title = title
		self.ancestors = []
		self.parents = False
		self.siblings = False
		self.children = False
		self.hierarchy = False
		self.ohandle = False


	@classmethod
	def get_parent(self, pid):
		'''
		Gets parent, returns (pid, title)
		'''
		# parent
		baseURL = "http://localhost/fedora/risearch"
		risearch_query = '''
		select $pid $title from <#ri> where
			<info:fedora/%s> 
			<wsudor:hasParent> 
			$pid
		and 
			$pid
			<dc:title>
			$title    
		order by $title

		''' % (pid)
		risearch_params = {
			'type': 'tuples',
			'lang': 'itql',
			'format': 'json',
			'limit':'',
			'dt': 'on',
			'query': risearch_query
		}
		r = fedora_handle.api.session.get(baseURL, params=risearch_params)
		# strip risearch namespace "info:fedora"
		parents_jsonString = r.text.replace('info:fedora/','')
		results = json.loads(parents_jsonString)

		# parse
		if len(results['results']) >= 1:
			return results['results'][0]
		else:
			return False


	@classmethod
	def get_siblings(self, pid):
		'''
		Gets all siblings
		'''
		# siblings
		baseURL = "http://localhost/fedora/risearch"
		risearch_query = '''
		select $pid $title from <#ri> where 
			<info:fedora/%s> 
			<wsudor:hasParent> 
			$parent
		and 
			$pid
			<wsudor:hasParent>
			$parent
		and 
			$pid
			<dc:title>
			$title
		order by $title

		''' % (pid)
		risearch_params = {
			'type': 'tuples',
			'lang': 'itql',
			'format': 'json',
			'limit':'',
			'dt': 'on',
			'query': risearch_query
		}

		r = fedora_handle.api.session.get(baseURL, params=risearch_params)
		# strip risearch namespace "info:fedora"
		sibling_jsonString = r.text.replace('info:fedora/','')
		sibling_dict = json.loads(sibling_jsonString)

		# reomve current PID from siblings
		for idx, val in enumerate(sibling_dict['results']):
			if val['pid'] == pid:
				del sibling_dict['results'][idx]
		return sibling_dict['results']


	@classmethod
	def get_children(self, pid):
		# children
		baseURL = "http://localhost/fedora/risearch"
		risearch_query = '''
		select $pid $title from <#ri> where 
			$pid
			<wsudor:hasParent> 
			<info:fedora/%s> 
		and
			$pid
			<dc:title>
			$title
		order by $title

		''' % (pid)
		risearch_params = {
			'type': 'tuples',
			'lang': 'itql',
			'format': 'json',
			'limit':'',
			'dt': 'on',
			'query': risearch_query
		}

		r = fedora_handle.api.session.get(baseURL, params=risearch_params)
		# strip risearch namespace "info:fedora"
		child_jsonString = r.text.replace('info:fedora/','')
		child_dict = json.loads(child_jsonString)
		return child_dict['results']


	@classmethod
	def get_ancestors(self, pid):
		'''
		Move upwards from immediate parents, divining vertical hierarchy.
		'''
		ancestors = []
		def recurisve_ancestor(pid):
			p = self.get_parent(pid)
			if p:
				p['level'] = len(ancestors) + 1                
				ancestors.insert(0,p)
				return recurisve_ancestor(p['pid'])
			else:
				return ancestors
		
		recurisve_ancestor(pid)
		return ancestors


	def save_hierarchy(self):
		'''
		This method queries ancestors and siblings, writes to JSON
		datastream of object
		'''
		self.hierarchy = {
			'self':{
				'pid':self.pid,
				'title':self.title
			},
			'ancestors':self.get_ancestors(self.pid),
			'siblings':self.get_siblings(self.pid),
			'children':self.get_children(self.pid)
		}
		self.ohandle = fedora_handle.get_object(self.pid)
		ds_handle = eulfedora.models.DatastreamObject(self.ohandle, "HIERARCHY", "HIERARCHY", mimetype="application/json", control_group="M")
		ds_handle.label = "HIERARCHY"
		ds_handle.content = json.dumps(self.hierarchy)
		ds_handle.save()
		return self.hierarchy


	def load_hierarchy(self, overwrite=False):
		self.ohandle = fedora_handle.get_object(self.pid)
		if 'HIERARCHY' in self.ohandle.ds_list and not overwrite:
			ds_handle = self.ohandle.getDatastreamObject('HIERARCHY')
			self.hierarchy = json.loads(ds_handle.content)
		else:
			self.hierarchy = self.save_hierarchy()
		return self.hierarchy


##################################################################   
# Solr / dataTables connector
##################################################################
# Inspired by: https://github.com/Pegase745/sqlalchemy-datatables


class DT(object):

	'''
	Scaffolding for DT response
	'''

	def __init__(self):
		self.draw = None,
		self.recordsTotal = None,
		self.recordsFiltered = None,
		self.data = []
		self.facets = []
		self.search_params = None


class SolrDT(object):

	'''
	Order of operations:
		- init 
		- query
		- filter / slice / order / etc.
		- build response
		- return json
	'''

	def __init__(self, solr_handle, DTinput):

		logging.debug("initializing SolrDT connector")

		# solr handle
		self.solr_handle = solr_handle

		# dictionary INPUT DataTables ajax
		self.DTinput = DTinput
		logging.debug("%s" % self.DTinput)

		# dictionary OUTPUT to DataTables
		self.DToutput = DT().__dict__
		self.DToutput['draw'] = DTinput['draw']

		self.search_params = { 
			'q': '*:*',
			'sort': None,
			'start': 0,
			'rows': 10,
			'fq': [],
			'fl': [ "id", "dc*", "rels*", "human*", "obj*", "last_modified"],
			'wt': 'json',
			'facet': True,
			'facet.mincount': 1,
			'facet.limit': -1,
			'facet.field': [
				"human_hasContentModel",
				"human_isMemberOfCollection"
			],
			'facet.sort': 'index',
			'stats':True,
			'stats.field':'obj_size_fedora_i'
		}

		# query and build response
		self.build_response()


	def filter(self):
		logging.debug('applying filters...')

		# apply search term as "q" if found in DTinput['search']['value']
		if self.DTinput['search']['value'] != '':
			self.search_params['q'] = self.DTinput['search']['value']

		# iterate through columns, look for facet filter
		for column in self.DTinput['columns']:
			if column['search']['value'] != '':
				fq_filter = "%s:%s" % ( column['name'], column['search']['value'].replace(" ","\\ ") )
				logging.debug('adding facet filter: %s' % fq_filter)
				self.search_params['fq'].append(fq_filter.encode("utf-8"))


	def sort(self):
		
		logging.debug('sorting...')
		'''
		'''

		sort_fields = []

		# get sort column
		for order in self.DTinput['order']:
			sort_field = self.DTinput['columns'][order['column']]['name']
			sort_dir = order['dir']
			sort_syntax = "%s %s" % (sort_field, sort_dir)
			logging.debug("adding sort: %s" % (sort_syntax))
			sort_fields.append(sort_syntax)
			concat_sort_string = ", ".join(sort_fields)
			logging.debug("%s" % concat_sort_string)

		# add to search_params
		self.search_params['sort'] = concat_sort_string


	def paginate(self):

		logging.debug('paginating...')

		# update start
		self.search_params['start'] = self.DTinput['start']
		self.search_params['rows'] = self.DTinput['length']


	def build_response(self):

		logging.debug('building query...')

		# total count
		ts = self.solr_handle.search(**{'q':'*:*'})

		# update DToutput
		self.DToutput['recordsTotal'] = ts.total_results

		# run sub-functions that tailor the default_params
		self.filter()
		self.sort()
		self.paginate()

		# debug
		logging.debug("%s" % self.search_params)

		# excecute search
		s = self.solr_handle.search(**self.search_params)

		# build DToutput
		self.DToutput['recordsFiltered'] = s.total_results

		# iterate through rows and add to 'data'
		if self.DToutput['recordsFiltered'] > 0:
			logging.debug('iterate through result set, add to response...')
			for doc in s.documents:

				ordered_fields = [
					doc['id']
				]

				# title
				if 'dc_title' in doc.keys():
					ordered_fields.append(self.truncate(480, doc['dc_title'][0]))
				else:
					ordered_fields.append("None")

				# description
				if 'dc_description' in doc.keys():
					ordered_fields.append(self.truncate(480, doc['dc_description'][0]))
				else:
					ordered_fields.append("None")

				# collection
				if 'human_isMemberOfCollection' in doc.keys():
					ordered_fields.append( ", ".join(doc['human_isMemberOfCollection']) )
				else:
					ordered_fields.append("None")

				# collection
				if 'human_hasContentModel' in doc.keys():
					ordered_fields.append( ", ".join(doc['human_hasContentModel']) )
				else:
					ordered_fields.append("None")

				# return placeholder for actions
				ordered_fields.append("None")

				# return as list of values for DT
				self.DToutput['data'].append(ordered_fields)



			# add facet information
			self.DToutput['facets'] = s.facets['facet_fields']

			# add facet information
			self.DToutput['stats'] = s.stats

			# add search_params
			self.DToutput['search_params'] = self.search_params

		else:
			logging.debug('none found for search parameters...')


	def to_json(self):

		return json.dumps(self.DToutput)


	def truncate(self, chars, input):
		
		if len(input) > chars:
			return "%s..." % input[0:chars]
		else:
			return input











