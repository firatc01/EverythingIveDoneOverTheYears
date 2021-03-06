import datetime
import settings
import fnmatch
import cStringIO as StringIO
import zipfile
import re
import urllib

from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.http import HttpResponseNotFound
from django.http import HttpResponseBadRequest
from django.template import loader, Context, RequestContext
from django.utils.encoding import smart_unicode
from django.contrib.auth.decorators import login_required
from django import forms
from django.shortcuts import render_to_response

from dj.models import *
from dj.widgets import ColorPickerWidget
import iaa
import util



@login_required
def start(request):
    annotator=Annotator.objects.filter(id=request.user.id)
    if not annotator:
        annotator = Annotator(**request.user.__dict__)
        annotator.save()
    if request.user.is_superuser: # if user is an administrator
        return projectList(request)
    else: # otherwise, user is an annotator
        #return error if this is not an annotator
        return index(request)

@login_required
def index(request):
    annotator = Annotator.objects.filter(id=request.user.id) # attempt to retrieve annotator info
    if len(annotator) == 0:
        return HttpResponseForbidden('Error: You are not an annotator') # if user is not an annotator, respond with forbidden
    annotator = annotator[0]
    doc_list = annotator.documents.all().order_by('-create_date') # attempt to retrieve annotator's documents
    for d in doc_list:
        submissions=Submission.objects.filter(document=d,annotator=annotator)
        if submissions:
            d.submit_date=submissions[0].submit_date
        else:
            d.submit_date=None
    t = loader.get_template('dj/index.html')
    c = RequestContext(request, {
    'doc_list': doc_list,
    'superuser':request.user.is_superuser
    })
    return HttpResponse(t.render(c))


# retrieve a specific document with annotations
@login_required
def documentByAnnotator(request, document_id, annotator_id=None, error=None):
    if annotator_id and request.user.is_superuser:
        annotator = Annotator.objects.filter(id=annotator_id)[0]
    else:
        annotator = Annotator.objects.filter(id=request.user.id)[0]   
    doc = Document.objects.filter(id=document_id)[0]
    annotations=Annotation.objects.filter(document=doc, annotator=annotator)
    annotation_types=AnnotationType.objects.filter(project=doc.project)
    t = loader.get_template('dj/doc.html')
    doc.text=util.htmlFormat(doc.text, annotations)
    doc.title=util.htmlFormat(doc.title, [])
    submissions=Submission.objects.filter(document=doc, annotator=annotator)
    if submissions:
        doc.submit_date=submissions[0].submit_date
    else:
        doc.submit_date=None
    c = RequestContext(request, {
    'doc': doc,
    'annotation_types':annotation_types,
    'annotator':request.user,
    'error_message': error,})
    return HttpResponse(t.render(c))


@login_required
def updateAnnotation(request):
    document_id=request.POST['document_id']
    indices=request.POST['indices']
    annotation_type_id=request.POST['category_id']
    document=Document.objects.get(id=document_id)
    annotation_id=indices.split('_')[1]
    annotation=Annotation.objects.get(id=annotation_id)

    if annotation_type_id == 'Delete':
        annotation.delete()
    else:
        annotation_type=AnnotationType.objects.get(id=annotation_type_id)
        annotation.annotation_type=annotation_type
        annotation.save()
    return HttpResponse('success: %s %s %s %s %s'%(dir(annotation), document_id, indices, annotation.begin_index, annotation))


@login_required
def newAnnotation(request):
    document_id=int(request.POST['document_id'])
    text=request.POST['newNec']
    annotation_id=int(request.POST['newNecCategoryId'])

    if annotation_id == 'Delete':
        return documentByAnnotator(request, document_id, annotator_id=request.user.id, error=None)
      
    if not text:
        return documentByAnnotator(request, document_id, annotator_id=request.user.id, error="Please select text to add new anntations")
    annotator=Annotator.objects.get(id=request.user.id)

    annotation_type=AnnotationType.objects.get(id=int(annotation_id))

    document=Document.objects.get(id=document_id)
    annotations = Annotation.objects.filter(document=document, annotator=annotator)

    indices=util.findIndices(document.text, text)


    for ind in indices:
        if Annotation.objects.filter(document=document, begin_index=ind[0], end_index=ind[1], annotator=annotator):
            continue
        begin=ind[0]
        end=ind[1]
        allNamedEntities=Annotation.objects.filter(document=document, annotator=annotator)
        for absNE in allNamedEntities:
            if util.overlap((absNE.begin_index, absNE.end_index), (ind[0],ind[1])):
                absNE.delete()
        #add new one
        annotation  = Annotation(document=document, annotation=text, begin_index=begin, end_index=end, annotation_type=annotation_type, annotator=annotator)
        annotation.save()

    return documentByAnnotator(request, document_id, annotator_id=request.user.id, error=None)

    

def iaaStats(request,annotator_id1=None,annotator_id2=None, project_id=None,error=None):
    if not annotator_id1:
        project_id=request.POST['project_id']
        if not request.POST.has_key('annotator1') or not request.POST.has_key('annotator2'):
            return projectEdit(request, project_id=project_id, error="Please Select 2 annotators to view IAA.")
        annotator_id1=request.POST['annotator1']
        annotator_id2=request.POST['annotator2']
    annotator1=Annotator.objects.get(id=annotator_id1)
    annotator2=Annotator.objects.get(id=annotator_id2)
    p=Project.objects.get(id=project_id)
    iaaStats=iaa.iaa(annotator1,annotator2,p)
    annotation_types=filter(lambda x: x.type,AnnotationType.objects.filter(project=p))
    t = loader.get_template('dj/stats.html')
    c = RequestContext(request, {
    'iaaStats': iaaStats,
    'annotation_types':annotation_types,
    'annotator2':annotator2,
    'annotator1':annotator1,
    'project':p,
    'error_message': error,})
    return HttpResponse(t.render(c))

def docCompare(request, document_id, annotator_id1, annotator_id2, error=None):
    annotator1=Annotator.objects.get(id=annotator_id1)
    annotator2=Annotator.objects.get(id=annotator_id2)
    doc1=Document.objects.get(id=document_id)
    annotations1=Annotation.objects.filter(document=doc1,annotator__id=annotator_id1)
    annotations2=Annotation.objects.filter(document=doc1,annotator__id=annotator_id2)
    doc2=Document.objects.get(id=document_id)
    doc1.text=util.htmlFormat(doc1.text,annotations1)
    doc2.text=util.htmlFormat(doc2.text,annotations2)
    doc1.title=doc2.title=util.htmlFormat(doc1.title,[])
    annotation_types=filter(lambda x: x.type,AnnotationType.objects.filter(project=doc1.project))
    c = RequestContext(request, {
    'doc1': doc1,
    'doc2': doc2,
    'annotation_types':annotation_types,
    'annotator1':annotator1,
    'annotator2':annotator2,
    'error_message': error,})
    t = loader.get_template('dj/docCompare.html')
    return HttpResponse(t.render(c))


class UploadFileForm(forms.Form):
    file = forms.FileField()

@login_required
def saveAnnotationType(request, project_id=None):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    title = urllib.unquote_plus(request.POST['title']).strip()
    desc = urllib.unquote_plus(request.POST['desc']).strip()
    color = urllib.unquote_plus(request.POST['color'])
    project=Project.objects.get(id=project_id)
    if (title or desc):
        if (not title or not desc):
            return projectEdit(request, project_id=project_id, error="Annotation Type title and description are required values.")
        ann = AnnotationType(type=title, description=desc, color=color, project=project)
        ann.save()
    annotationTypes=AnnotationType.objects.filter(project=project)
    for a in annotationTypes:
        if request.POST.has_key('del_ann_%s'%a.id):
            annotations=Annotation.objects.filter(annotation_type=a)
            for an in annotations:
                an.delete()
            a.delete()
    return projectEdit(request, project_id=project_id)

@login_required
def upload_file(request, project_id=None):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    if not request.FILES.has_key('fileToUpload') or not request.FILES['fileToUpload']:
        return projectEdit(request,project_id=project_id,error="Please select a file to upload (supported formats are .zip and .txt).")
    f = request.FILES['fileToUpload']
    if (not f.name.endswith('.txt')) and (not f.name.endswith('.zip')):
        return projectEdit(request,project_id=project_id,error="Please select a file to upload (supported formats are .zip and .txt).")
    project = Project.objects.get(id=project_id)
    if fnmatch.fnmatch(f.name, '*.txt'):
        doc = Document()
        doc.title = f.name
        doc.create_date = str(datetime.datetime.now())
        doc.project = project
        doc.text = f.read()
        doc.text = smart_unicode(doc.text, encoding='utf-8', strings_only=False, errors='ignore')
        doc.save()
    if fnmatch.fnmatch(f.name, '*.zip'):
        zipdata = ""
        for chunk in f.chunks(): # don't blow chunks now..
            zipdata += chunk # haha, get it? chunks? hah.
        zip = zipfile.ZipFile(StringIO.StringIO(zipdata))
        for file in zip.namelist():
            doc = Document()
            doc.title = file
            doc.create_date = str(datetime.datetime.now())
            doc.project = Project.objects.get(id=project_id)
            doc.text = zip.read(file).strip()
            doc.text = smart_unicode(doc.text, encoding='utf-8', strings_only=False, errors='ignore')
            doc.save()
        zip.close()
    return projectEdit(request, project_id=project_id)   

@login_required
def projectList(request, error=None):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You are not an administrator.")
    annotators=Annotator.objects.all()   
    return render_to_response("dj/project-list.html", {'project_list': Project.objects.all(), 'annotator_list': annotators, 'error_message':error}, context_instance=RequestContext(request))


@login_required
def projectDelete(request):
    if not request.user.is_superuser:
       return HttpResponseForbidden("Only admins can edit projects.")
    project_ids=request.POST.getlist("project_ids")
    error=""
    for id in project_ids:
        project=Project.objects.get(id=id)
        if project.annotators.all() or Document.objects.filter(project=project):
            error="Only empty projects can be deleted. Please remove all documents and associated annotators first"
            return projectList(request, error=error)
        else:
            project.delete()
    return projectList(request, error=error)


@login_required
def projectSave(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    project_name=request.POST['project_title']
    project_id=request.POST['project_id'].strip()
    if len(project_name)>300:
        return  projectEdit(request, project_id=project_id, error="Project name exceed the maximum of 300 characters")
    if project_id:     
        project=Project.objects.get(id=project_id)
        project.name=project_name
    else:
        project=Project(name=project_name)
    if request.POST.has_key('allow_chains') and request.POST['allow_chains']:
        project.allow_chains=True
    else:
        project.allow_chains=False
    project.save()
    documents=Document.objects.filter(project=project)
    allAnnotators=Annotator.objects.all()
    for a in allAnnotators:
        if request.POST.has_key("projectAnnotator_%s"%a.id):
            project.annotators.add(a)
        else:
            project.annotators.remove(a)
    project.save()   
    return projectEdit(request, project_id=project.id)

@login_required
def projectSaveDocuments(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    project_id=request.POST['project_id'].strip()
    project=Project.objects.get(id=project_id)
    documents=Document.objects.filter(project=project)
    for doc in documents:
        if request.POST.has_key('del_%s'%doc.id):
            Annotation.objects.filter(document=doc).delete()
            doc.delete()
        else:
            annotators = Annotator.objects.filter(project=project)
            for i in range(1,len(annotators)+1):
                annotator=annotators[i-1]
                if request.POST.has_key('annotator_%s_%s'%(doc.id,i)):
                    #add annototar
                    annotator.documents.add(doc)
                else:
                    #delete it
                    annotator.documents.remove(doc)
                annotator.save()
    return projectEdit(request, project_id=project.id)



@login_required
def projectEdit(request, project_id=None, error=None):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    project=None
    user_list = []
    form = UploadFileForm()
    document_list=[]
    annotation_types=[]
    allAnnotators=Annotator.objects.all()

    if project_id:
        project = Project.objects.get(id=project_id)
        document_list = Document.objects.filter(project=project)
        user_list = project.annotators.all()
        for a in allAnnotators:
            if a in user_list:
                a.inProject=True
            else:
                a.inProject=False
        for doc in document_list:
            annotators = Annotator.objects.filter(documents=doc)
            doc.user_list=[]
            for a in user_list:
                if a in annotators:
                    doc.user_list.append(True)
                else:
                    doc.user_list.append(False)
        annotation_types = AnnotationType.objects.filter(project=project) 
    return render_to_response("dj/project-edit.html",
                              {'project' : project,
                               'user_list': user_list,
                               'document_list' : document_list,
                               'annotation_types' : annotation_types,
                               'annotators':allAnnotators,
                              'error_message': error},
                              context_instance=RequestContext(request))

@login_required
def docSubmit(request):
    doc_id = request.POST['doc_id']
    annotator = Annotator.objects.get(id=request.user.id)
    document=Document.objects.get(id=doc_id)
    submission=Submission(document=document, annotator=annotator, submit_date=datetime.datetime.now())
    submission.save()
    return documentByAnnotator(request, doc_id)



@login_required
def editAnnotator(request, annotator_id=None):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Error: You must be an administrator to use this form")
    if request.method == 'POST': # If the form has been submitted...
        newPass=True
        if request.POST.has_key('annotator_id'):
            annotator_id=request.POST['annotator_id']
            annotator=Annotator.objects.get(id=annotator_id)
            if (request.POST.has_key('password') and annotator.password==request.POST['password']):
                newPass=False
            form = AnnotatorForm(request.POST, instance=annotator)
        else:
            form = AnnotatorForm(request.POST) # A form bound to the POST data
        if form.is_valid(): # All validation rules pass
            annotator=form.save()
            if newPass:
                annotator.set_password(annotator.password)
            annotator.save()
    elif annotator_id:
        a=Annotator.objects.get(id=annotator_id)
        form = AnnotatorForm(instance=a)
    else:
        form = AnnotatorForm() # An unbound form
    return render_to_response('dj/annotator.html', {
        'form': form,
        },
        context_instance=RequestContext(request)
    )

@login_required
def deleteAnnotator(request):
    if not request.user.is_superuser:
       return HttpResponseForbidden("Only admins can edit projects.")
    annotator_ids=request.POST.getlist('annotator_ids')
    error=""
    for id in annotator_ids:
        annotator=Annotator.objects.get(id=id)
        if annotator.documents.all():
            error="Annotator %s has assigned documents and cannot be deleted. Please remove assigned documents first."%annotator.username
            return projectList(request, error=error)
        else:
            annotator.delete()
    return projectList(request, error=error)

