#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import mimetypes
import json
import uuid
from PIL import Image
import time
import traceback
import sys
import re
from bs4 import BeautifulSoup
import requests

# library for working with LOC BagIt standard 
import bagit

# celery
from cl.cl import celery

# eulfedora
import eulfedora

# WSUDOR
import WSUDOR_ContentTypes
from WSUDOR_Manager.solrHandles import solr_handle
from WSUDOR_Manager.fedoraHandles import fedora_handle
from WSUDOR_Manager import redisHandles, helpers, utilities
from WSUDOR_API.functions.packagedFunctions import singleObjectPackage

# import manifest factory instance
from inc.manifest_factory import iiif_manifest_factory_instance

# derivatives
from inc.derivatives import JP2DerivativeMaker


# helper function for natural sorting
def natural_sort_key(s, _nsre=re.compile('([0-9]+)')):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(_nsre, s)] 


class WSUDOR_WSUebook(WSUDOR_ContentTypes.WSUDOR_GenObject):

	# static values for class
	label = "WSUeBook"
	description = "The WSUDOR_WSUebook content type models most print (but some born digital) resources we have created digital components for each page.  This includes a page image, ALTO XML with information about the location of words on the page, a thumbnail, a PDF (with embedded text), and HTML that semi-closely matches the original formatting (suitable for flowing text).  These objects are best viewed with our eTextReader."
	Fedora_ContentType = "CM:WSUebook"

	def __init__(self, object_type=False, content_type=False, payload=False):
		
		# run __init__ from parent class
		WSUDOR_ContentTypes.WSUDOR_GenObject.__init__(self,object_type, content_type, payload)
		
		# Add WSUDOR_Image struct_requirements to WSUDOR_Object instance struct_requirements
		self.struct_requirements['WSUDOR_WSUebook'] = {
			"datastreams":[
				{
					"id":"DUMMY_TEXT",
					"purpose":"DUMMY_TEXT",
					"mimetype":"DUMMY_TEXT"
				}				
			],
			"external_relationships":[]
		}

		# empty destinations for concatenated content
		self.html_concat = ''


	# perform ingestTest
	def validIngestBag(self):

		def report_failure(failure_tuple):
			if results_dict['verdict'] == True : results_dict['verdict'] = False
			results_dict['failed_tests'].append(failure_tuple)

		# reporting
		results_dict = {
			"verdict":True,
			"failed_tests":[]
		}

		# check that content_type is a valid ContentType				
		if self.__class__ not in WSUDOR_ContentTypes.WSUDOR_GenObject.__subclasses__():
			report_failure(("Valid ContentType","WSUDOR_Object instance's ContentType: {content_type}, not found in acceptable ContentTypes: {ContentTypes_list} ".format(content_type=self.content_type,ContentTypes_list=WSUDOR_ContentTypes.WSUDOR_GenObject.__subclasses__())))				

		# finally, return verdict
		return results_dict


	# ingest 
	def ingestBag(self):

		#----------------- GENERIC INGEST PROCEDURES, CAN BE FOLDED INTO WSUDOR_Object -----------------#
		
		if self.object_type != "bag":
			raise Exception("WSUDOR_Object instance is not 'bag' type, aborting.")


		# attempt to ingest bag / object
		try:			
			
			self.ohandle = fedora_handle.get_object(self.objMeta['id'],create=True)
			self.ohandle.save()

			# set base properties of object
			self.ohandle.label = self.objMeta['label']

			# write POLICY datastream
			# NOTE: 'E' management type required, not 'R'
			print "Using policy:",self.objMeta['policy']
			policy_suffix = self.objMeta['policy'].split("info:fedora/")[1]
			policy_handle = eulfedora.models.DatastreamObject(self.ohandle,"POLICY", "POLICY", mimetype="text/xml", control_group="E")
			policy_handle.ds_location = "http://localhost/fedora/objects/{policy}/datastreams/POLICY_XML/content".format(policy=policy_suffix)
			policy_handle.label = "POLICY"
			policy_handle.save()

			# write objMeta as datastream
			objMeta_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "OBJMETA", "Ingest Bag Object Metadata", mimetype="application/json", control_group='M')
			objMeta_handle.label = "Ingest Bag Object Metadata"
			file_path = self.Bag.path + "/data/objMeta.json"
			objMeta_handle.content = open(file_path)
			objMeta_handle.save()

			# -------------------------------------- RELS-EXT ---------------------------------------#

			# write explicit RELS-EXT relationships			
			for relationship in self.objMeta['object_relationships']:
				print "Writing relationship:",str(relationship['predicate']),str(relationship['object'])
				self.ohandle.add_relationship(str(relationship['predicate']),str(relationship['object']))
			
			# writes derived RELS-EXT			
			# isRepresentedBy
			self.ohandle.add_relationship("http://digital.library.wayne.edu/fedora/objects/wayne:WSUDOR-Fedora-Relations/datastreams/RELATIONS/content/isRepresentedBy",self.objMeta['isRepresentedBy'])
			
			# hasContentModel
			content_type_string = str("info:fedora/CM:"+self.objMeta['content_type'].split("_")[1])
			print "Writing ContentType relationship:","info:fedora/fedora-system:def/relations-external#hasContentModel",content_type_string
			self.ohandle.add_relationship("info:fedora/fedora-system:def/relations-external#hasContentModel",content_type_string)

			# -------------------------------------- RELS-EXT ---------------------------------------#

			# write MODS datastream if MODS.xml exists
			if os.path.exists(self.Bag.path + "/data/MODS.xml"):
				MODS_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "MODS", "MODS descriptive metadata", mimetype="text/xml", control_group='M')
				MODS_handle.label = "MODS descriptive metadata"
				file_path = self.Bag.path + "/data/MODS.xml"
				MODS_handle.content = open(file_path)
				MODS_handle.save()

			else:
				# write generic MODS datastream
				MODS_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "MODS", "MODS descriptive metadata", mimetype="text/xml", control_group='M')
				MODS_handle.label = "MODS descriptive metadata"

				raw_MODS = '''
<mods:mods xmlns:mods="http://www.loc.gov/mods/v3" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="3.4" xsi:schemaLocation="http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/v3/mods-3-4.xsd">
  <mods:titleInfo>
    <mods:title>{label}</mods:title>
  </mods:titleInfo>
  <mods:identifier type="local">{identifier}</mods:identifier>
  <mods:extension>
    <PID>{PID}</PID>
  </mods:extension>
</mods:mods>
				'''.format(label=self.objMeta['label'], identifier=self.objMeta['id'].split(":")[1], PID=self.objMeta['id'])
				print raw_MODS
				MODS_handle.content = raw_MODS		
				MODS_handle.save()


			# create derivatives and write datastreams by using processing functions defined below
			
			# concat variables
			html_concat =''

			for ds in self.objMeta['datastreams']:
				# # ---------- DEBUG REMOVE ---------- 
				# if int(ds['order']) < 3:
				# # ---------- DEBUG REMOVE ---------- 
				if ds['ds_id'].startswith('IMAGE'):
					self.processImage(ds)
				if ds['ds_id'].startswith('HTML'):
					self.processHTML(ds)
				if ds['ds_id'].startswith('ALTOXML'):
					self.processALTOXML(ds)

			# write generic thumbnail and preview
			rep_handle = eulfedora.models.DatastreamObject(self.ohandle, "THUMBNAIL", "THUMBNAIL", mimetype="image/jpeg", control_group="R")
			rep_handle.ds_location = "http://digital.library.wayne.edu/fedora/objects/{pid}/datastreams/{ds_id}_THUMBNAIL/content".format(pid=self.ohandle.pid, ds_id=self.objMeta['isRepresentedBy'])
			rep_handle.label = "THUMBNAIL"
			rep_handle.save()

			# generate full HTML, text, and PDF
			# HTML (based on concatenated HTML from self.html_concat)
			html_full_handle = eulfedora.models.DatastreamObject(self.ohandle, "HTML_FULL", "Full HTML for item", mimetype="text/html", control_group="M")
			html_full_handle.label = "Full HTML for item"
			html_full_handle.content = self.html_concat.encode('utf-8')
			html_full_handle.save()

			# PDF - create PDF on disk and upload
			# use pdftk to write temp PDF file			
			temp_filename = "/tmp/Ouroboros/"+str(uuid.uuid4())+".pdf"
			os.system("pdftk {obj_dir}/data/datastreams/*.pdf cat output {temp_filename}".format(obj_dir=self.Bag.path, temp_filename=temp_filename))			
			pdf_full_handle = eulfedora.models.DatastreamObject(self.ohandle, "PDF_FULL", "Fulltext PDF for item", mimetype="application/pdf", control_group="M")
			pdf_full_handle.label = "Fulltext PDF for item"
			pdf_full_handle.content = open(temp_filename)
			pdf_full_handle.save()

			# save and commit object before finishIngest()
			final_save = self.ohandle.save()

			# finish generic ingest
			return self.finishIngest(gen_manifest=True)

		# exception handling
		except Exception,e:
			print traceback.format_exc()
			print "Ingest Error:",e
			return False


	# --- Define processors for components (image, html, pdf, ALTO xml) ---------------------------------------#
	def processImage(self, ds):

		print "Processing derivative"
		file_path = self.Bag.path + "/data/datastreams/" + ds['filename']
		print "Looking for:",file_path

		# original
		orig_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "{ds_id}".format(ds_id=ds['ds_id']), ds['label'], mimetype=ds['mimetype'], control_group='M')
		orig_handle.label = ds['label']
		orig_handle.content = open(file_path)
		orig_handle.save()				
		
		# make thumb			
		temp_filename = "/tmp/Ouroboros/"+str(uuid.uuid4())+".jpg"
		im = Image.open(file_path)
		width, height = im.size
		max_width = 200	
		max_height = 200
		# run through filter
		im = imMode(im)
		im.thumbnail((max_width, max_height), Image.ANTIALIAS)
		im.save(temp_filename,'JPEG')
		thumb_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "{ds_id}_THUMBNAIL".format(ds_id=ds['ds_id']), "{label}_THUMBNAIL".format(label=ds['label']), mimetype="image/jpeg", control_group='M')
		thumb_handle.label = "{label}_THUMBNAIL".format(label=ds['label'])
		thumb_handle.content = open(temp_filename)
		thumb_handle.save()
		os.system('rm {temp_filename}'.format(temp_filename=temp_filename))		

		# make jp2
		temp_filename = "/tmp/Ouroboros/"+str(uuid.uuid4())+".jp2"
		os.system("convert {input} {output}[256x256]".format(input=file_path,output=temp_filename))
		jp2_handle = eulfedora.models.FileDatastreamObject(self.ohandle, "{ds_id}_JP2".format(ds_id=ds['ds_id']), "{label}_JP2".format(label=ds['label']), mimetype="image/jp2", control_group='M')
		jp2_handle.label = "{label}_JP2".format(label=ds['label'])
		try:
			jp2_handle.content = open(temp_filename)
		except:
			# sometimes jp2 creation results in two files, look for first one in this instance
			temp_filename = temp_filename.split(".")[0]
			temp_filename = temp_filename + "-0.jp2"
			jp2_handle.content = open(temp_filename)
		jp2_handle.save()
		os.system('rm {temp_filename}'.format(temp_filename=temp_filename))



		# -------------------------------------- RELS-INT ---------------------------------------#

		# add to RELS-INT
		fedora_handle.api.addRelationship(self.ohandle,'info:fedora/{pid}/{ds_id}'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']),'info:fedora/fedora-system:def/relations-internal#isPartOf','info:fedora/{pid}'.format(pid=self.ohandle.pid))
		fedora_handle.api.addRelationship(self.ohandle,'info:fedora/{pid}/{ds_id}_THUMBNAIL'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']),'info:fedora/fedora-system:def/relations-internal#isThumbnailOf','info:fedora/{pid}/{ds_id}'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']))
		fedora_handle.api.addRelationship(self.ohandle,'info:fedora/{pid}/{ds_id}_JP2'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']),'info:fedora/fedora-system:def/relations-internal#isJP2Of','info:fedora/{pid}/{ds_id}'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']))

		# if order present, get order and write relationship. 
		if 'order' in ds:
			fedora_handle.api.addRelationship(self.ohandle,'info:fedora/{pid}/{ds_id}'.format(pid=self.ohandle.pid,ds_id=ds['ds_id']),'info:fedora/fedora-system:def/relations-internal#isOrder', ds['order'], isLiteral=True)


	def processHTML(self, ds):
		print "Processing HTML"
		file_path = self.Bag.path + "/data/datastreams/" + ds['filename']
		print "Looking for:",file_path
		generic_handle = eulfedora.models.FileDatastreamObject(self.ohandle, ds['ds_id'], ds['label'], mimetype=ds['mimetype'], control_group='M')
		generic_handle.label = ds['label']
		generic_handle.content = open(file_path)
		generic_handle.save()

		# add HTML to self.html_concat
		fhand = open(file_path)
		html_parsed = BeautifulSoup(fhand)
		print "HTML document parsed..."
		#sets div with page_ID
		self.html_concat = self.html_concat + '<div id="page_ID_{order}" class="html_page">'.format(order=ds['order'])
		#Set in try / except block, as some HTML documents contain no elements within <body> tag
		try:
			for block in html_parsed.body:				
				self.html_concat = self.html_concat + unicode(block)				
		except:
			print "<body> tag is empty, skipping. Adding page_ID anyway."
			
		#closes page_ID / div
		self.html_concat = self.html_concat + "</div>"
		fhand.close()


		# index in Solr bookreader core
		data = {
			"literal.id" : self.objMeta['identifier']+"_OCR_HTML_"+ds['order'],
			"literal.ItemID" : self.objMeta['identifier'],
			"literal.page_num" : ds['order'],
			"fmap.content" : "OCR_text",
			"commit" : "true"
		}
		files = {'file': open(file_path, 'rb')}
		r = requests.post("http://localhost/solr4/bookreader/update/extract", data=data, files=files)		


	def processALTOXML(self, ds):
		print "Processing ALTO XML"
		file_path = self.Bag.path + "/data/datastreams/" + ds['filename']
		print "Looking for:",file_path
		generic_handle = eulfedora.models.FileDatastreamObject(self.ohandle, ds['ds_id'], ds['label'], mimetype=ds['mimetype'], control_group='M')
		generic_handle.label = ds['label']
		generic_handle.content = open(file_path)
		generic_handle.save()


	# ingest 
	def migrate(self):

		'''
		This function will migrate bags from our multiple-object model (old) to a single-object model (new).
		This will require the following work:
			- export multi-object to single directory
				- consider /repository for this amount of data
			- write objMeta.json file for that object (first time)
			- BagIt
			- create ingest method for single-object ebooks
			- ingest!
			- purge old book?
		'''

		return True


	# ingest image type
	def genIIIFManifest(self):

		# run singleObjectPackage
		'''
		A bit of a hack here: creating getParams{} with pid as list[] as expected by singleObjectPackage(),
		simulates normal WSUDOR_API use of singleObjectPackage()
		'''
		getParams = {}
		getParams['PID'] = [self.pid]

		# run singleObjectPackage() from API
		single_json = json.loads(singleObjectPackage(getParams))
			
		# create root mani obj
		try:
			manifest = iiif_manifest_factory_instance.manifest( label=single_json['objectSolrDoc']['mods_title_ms'][0] )
		except:
			manifest = iiif_manifest_factory_instance.manifest( label="Unknown Title" )
		manifest.viewingDirection = "left-to-right"

		# build metadata
		'''
		Order of preferred fields is the order they will show on the viewer
		NOTE: solr items are stored here as strings so they won't evaluate
		'''
		preferred_fields = [
			("Title", "single_json['objectSolrDoc']['mods_title_ms'][0]"),
			("Description", "single_json['objectSolrDoc']['mods_abstract_ms'][0]"),
			("Year", "single_json['objectSolrDoc']['mods_key_date_year'][0]"),
			("Item URL", "\"<a href='{url}'>{url}</a>\".format(url=single_json['objectSolrDoc']['mods_location_url_ms'][0])"),
			("Original", "single_json['objectSolrDoc']['mods_otherFormat_note_ms'][0]")
		]
		for field_set in preferred_fields:
			try:
				manifest.set_metadata({ field_set[0]:eval(field_set[1]) })
			except:
				print "Could Not Set Metadata Field, Skipping",field_set[0]
	
		# start anonymous sequence
		seq = manifest.sequence(label="default sequence")

		# get component parts		
		image_list = [ds for ds in self.ohandle.ds_list if ds.endswith('JP2')]
		image_list.sort(key=natural_sort_key)
		print image_list

		# iterate through component parts
		for image in image_list:
			
			print "adding",image
			
			# generate obj|ds self.pid as defined in loris TemplateHTTP extension
			fedora_http_ident = "fedora:%s|%s" % (self.pid,image)
			# fedora_http_ident = "%s|%s" % (self.pid,image) #loris_dev


			# Create a canvas with uri slug of page-1, and label of Page 1
			cvs = seq.canvas(ident=fedora_http_ident, label=image)

			# Create an annotation on the Canvas
			anno = cvs.annotation()

			# Add Image: http://www.example.org/path/to/image/api/p1/full/full/0/native.jpg
			img = anno.image(fedora_http_ident, iiif=True)

			# OR if you have a IIIF service:
			img.set_hw_from_iiif()

			cvs.height = img.height
			cvs.width = img.width


		# insert into Redis and return JSON string
		print "Inserting manifest for",self.pid,"into Redis..."
		redisHandles.r_iiif.set(self.pid,manifest.toString())
		return manifest.toString()


# helpers
'''
This might be where we can fix the gray TIFFs
'''
def imMode(im):
	# check for 16-bit tiffs
	print "Image mode:",im.mode				
	if im.mode in ['I;16','I;16B']:
		print "I;16 tiff detected, converting..."
		im.mode = 'I'
		im = im.point(lambda i:i*(1./256)).convert('L')
	# else if not RGB, convert
	elif im.mode != "RGB" :
		print "Converting to RGB"
		im = im.convert("RGB")

	return im























