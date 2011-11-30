#
# Copyright (C) 2007-2011 by Johan De Taeye, frePPLe bvba
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation; either version 2.1 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser
# General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

# file : $URL$
# revision : $LastChangedRevision$  $LastChangedBy$
# date : $LastChangedDate$

from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect, Http404
from django.views.decorators.csrf import csrf_protect
from django.utils import simplejson
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import iri_to_uri, force_unicode

from freppledb.input.models import Resource, Forecast, Operation, Location, SetupMatrix
from freppledb.input.models import Buffer, Customer, Demand, Parameter, Item, Load, Flow
from freppledb.input.models import Calendar, CalendarBucket, OperationPlan, SubOperation
from freppledb.input.models import Bucket, BucketDetail
from freppledb.common.report import GridReport, GridFieldBool, GridFieldLastModified, GridFieldDateTime
from freppledb.common.report import GridFieldText, GridFieldNumber, GridFieldInteger, GridFieldCurrency


class uploadjson:
  '''
  This class allows us to process json-formatted post requests.

  The current implementation is only temporary until a more generic REST interface
  becomes available in Django: see http://code.google.com/p/django-rest-interface/
  '''
  @staticmethod
  @csrf_protect
  @staff_member_required
  def post(request):
    try:
      # Validate the upload form
      if request.method != 'POST' or not request.is_ajax():
        raise Exception(_('Only ajax POST method allowed'))

      # Validate uploaded file is present
      if len(request.FILES)!=1 or 'data' not in request.FILES \
        or request.FILES['data'].content_type != 'application/json' \
        or request.FILES['data'].size > 1000000:
          raise Exception('Invalid uploaded data')

      # Parse the uploaded data and go over each record
      for i in simplejson.JSONDecoder().decode(request.FILES['data'].read()):
        try:
          entity = i['entity']

          # CASE 1: The maximum calendar of a resource is being edited
          if entity == 'resource.maximum':
            # Create a message
            try:
              msg = "capacity change for '%s' between %s and %s to %s" % \
                    (i['name'],i['startdate'],i['enddate'],i['value'])
            except:
              msg = "capacity change"
            # a) Verify permissions
            if not request.user.has_perm('input.change_resource'):
              raise Exception('No permission to change resources')
            # b) Find the calendar
            res = Resource.objects.using(request.database).get(name = i['name'])
            if not res.maximum_calendar:
              raise Exception('Resource "%s" has no maximum calendar' % res.name)
            # c) Update the calendar
            start = datetime.strptime(i['startdate'],'%Y-%m-%d')
            end = datetime.strptime(i['enddate'],'%Y-%m-%d')
            res.maximum_calendar.setvalue(
              start,
              end,
              float(i['value']) / (end - start).days,
              user = request.user)

          # CASE 2: The forecast quantity is being edited
          elif entity == 'forecast.total':
            # Create a message
            try:
              msg = "forecast change for '%s' between %s and %s to %s" % \
                      (i['name'],i['startdate'],i['enddate'],i['value'])
            except:
              msg = "forecast change"
            # a) Verify permissions
            if not request.user.has_perm('input.change_forecastdemand'):
              raise Exception('No permission to change forecast demand')
            # b) Find the forecast
            start = datetime.strptime(i['startdate'],'%Y-%m-%d')
            end = datetime.strptime(i['enddate'],'%Y-%m-%d')
            fcst = Forecast.objects.using(request.database).get(name = i['name'])
            # c) Update the forecast
            fcst.setTotal(start,end,i['value'])

          # All the rest is garbage
          else:
            msg = "unknown action"
            raise Exception(_("Unknown action type '%(msg)s'") % {'msg':entity})

        except Exception as e:
          messages.add_message(request, messages.ERROR, 'Error processing %s: %s' % (msg,e))

      # Processing went fine...
      return HttpResponse("OK",mimetype='text/plain')

    except Exception as e:
      print('Error processing uploaded data: %s %s' % (type(e),e))
      return HttpResponseForbidden('Error processing uploaded data: %s' % e)


class pathreport:
  '''
  A report showing the upstream supply path or following downstream a
  where-used path.
  The supply path report shows all the materials, operations and resources
  used to make a certain item.
  The where-used report shows all the materials and operations that use
  a specific item.
  '''

  @staticmethod
  def getPath(request, type, entity, downstream):
    '''
    A generator function that recurses upstream or downstream in the supply
    chain.

    todo: The current code only supports 1 level of super- or sub-operations.
    '''
    from django.core.exceptions import ObjectDoesNotExist
    if type == 'buffer':
      # Find the buffer
      try: root = [ (0, Buffer.objects.using(request.database).get(name=entity), None, None, None, Decimal(1)) ]
      except ObjectDoesNotExist: raise Http404("buffer %s doesn't exist" % entity)
    elif type == 'item':
      # Find the item
      try:
        root = [ (0, r, None, None, None, Decimal(1)) for r in Buffer.objects.filter(item=entity).using(request.database) ]
      except ObjectDoesNotExist: raise Http404("item %s doesn't exist" % entity)
    elif type == 'operation':
      # Find the operation
      try: root = [ (0, None, None, Operation.objects.using(request.database).get(name=entity), None, Decimal(1)) ]
      except ObjectDoesNotExist: raise Http404("operation %s doesn't exist" % entity)
    elif type == 'resource':
      # Find the resource
      try: root = Resource.objects.using(request.database).get(name=entity)
      except ObjectDoesNotExist: raise Http404("resource %s doesn't exist" % entity)
      root = [ (0, None, None, i.operation, None, Decimal(1)) for i in root.loads.using(request.database).all() ]
    else:
      raise Http404("invalid entity type %s" % type)

    # Note that the root to start with can be either buffer or operation.
    visited = []
    while len(root) > 0:
      level, curbuffer, curprodflow, curoperation, curconsflow, curqty = root.pop()
      yield {
        'buffer': curbuffer,
        'producingflow': curprodflow,
        'operation': curoperation,
        'level': abs(level),
        'consumingflow': curconsflow,
        'cumquantity': curqty,
        }

      # Avoid infinite loops when the supply chain contains cycles
      if curbuffer:
        if curbuffer in visited: continue
        else: visited.append(curbuffer)
      else:
        if curoperation and curoperation in visited: continue
        else: visited.append(curoperation)

      if downstream:
        # DOWNSTREAM: Find all operations consuming from this buffer...
        if curbuffer:
          start = [ (i, i.operation) for i in curbuffer.flows.filter(quantity__lt=0).select_related(depth=1).using(request.database) ]
        else:
          start = [ (None, curoperation) ]
        for cons_flow, curoperation in start:
          if not cons_flow and not curoperation: continue
          # ... and pick up the buffer they produce into
          ok = False

          # Push the next buffer on the stack, based on current operation
          for prod_flow in curoperation.flows.filter(quantity__gt=0).select_related(depth=1).using(request.database):
            ok = True
            root.append( (level+1, prod_flow.thebuffer, prod_flow, curoperation, cons_flow, curqty / prod_flow.quantity * (cons_flow and cons_flow.quantity * -1 or 1)) )

          # Push the next buffer on the stack, based on super-operations
          for x in curoperation.superoperations.select_related(depth=1).using(request.database):
            for prod_flow in x.operation.flows.filter(quantity__gt=0).using(request.database):
              ok = True
              root.append( (level+1, prod_flow.thebuffer, prod_flow, curoperation, cons_flow, curqty / prod_flow.quantity * (cons_flow and cons_flow.quantity * -1 or 1)) )

          # Push the next buffer on the stack, based on sub-operations
          for x in curoperation.suboperations.select_related(depth=1).using(request.database):
            for prod_flow in x.suboperation.flows.filter(quantity__gt=0).using(request.database):
              ok = True
              root.append( (level+1, prod_flow.thebuffer, prod_flow, curoperation, cons_flow, curqty / prod_flow.quantity * (cons_flow and cons_flow.quantity * -1 or 1)) )

          if not ok and cons_flow:
            # No producing flow found: there are no more buffers downstream
            root.append( (level+1, None, None, curoperation, cons_flow, curqty * cons_flow.quantity * -1) )
          if not ok:
            # An operation without any flows (on itself, any of its suboperations or any of its superoperations)
            for x in curoperation.suboperations.using(request.database):
              root.append( (level+1, None, None, x.suboperation, None, curqty) )
            for x in curoperation.superoperations.using(request.database):
              root.append( (level+1, None, None, x.operation, None, curqty) )

      else:
        # UPSTREAM: Find all operations producing into this buffer...
        if curbuffer:
          if curbuffer.producing:
            start = [ (i, i.operation) for i in curbuffer.producing.flows.filter(quantity__gt=0).select_related(depth=1).using(request.database) ]
          else:
            start = []
        else:
          start = [ (None, curoperation) ]
        for prod_flow, curoperation in start:
          if not prod_flow and not curoperation: continue
          # ... and pick up the buffer they produce into
          ok = False

          # Push the next buffer on the stack, based on current operation
          for cons_flow in curoperation.flows.filter(quantity__lt=0).select_related(depth=1).using(request.database):
            ok = True
            root.append( (level-1, cons_flow.thebuffer, prod_flow, cons_flow.operation, cons_flow, curqty / (prod_flow and prod_flow.quantity or 1) * cons_flow.quantity * -1) )

          # Push the next buffer on the stack, based on super-operations
          for x in curoperation.superoperations.select_related(depth=1).using(request.database):
            for cons_flow in x.operation.flows.filter(quantity__lt=0).using(request.database):
              ok = True
              root.append( (level-1, cons_flow.thebuffer, prod_flow, cons_flow.operation, cons_flow, curqty / (prod_flow and prod_flow.quantity or 1) * cons_flow.quantity * -1) )

          # Push the next buffer on the stack, based on sub-operations
          for x in curoperation.suboperations.select_related(depth=1).using(request.database):
            for cons_flow in x.suboperation.flows.filter(quantity__lt=0).using(request.database):
              ok = True
              root.append( (level-1, cons_flow.thebuffer, prod_flow, cons_flow.operation, cons_flow, curqty / (prod_flow and prod_flow.quantity or 1) * cons_flow.quantity * -1) )

          if not ok and prod_flow:
            # No consuming flow found: there are no more buffers upstream
            ok = True
            root.append( (level-1, None, prod_flow, prod_flow.operation, None, curqty / prod_flow.quantity) )
          if not ok:
            # An operation without any flows (on itself, any of its suboperations or any of its superoperations)
            for x in curoperation.suboperations.using(request.database):
              root.append( (level-1, None, None, x.suboperation, None, curqty) )
            for x in curoperation.superoperations.using(request.database):
              root.append( (level-1, None, None, x.operation, None, curqty) )

  @staticmethod
  @staff_member_required
  def viewdownstream(request, type, entity):
    return render_to_response('input/path.html', RequestContext(request,{
       'title': _('Where-used report for %(type)s %(entity)s') % {'type':_(type), 'entity':entity},
       'supplypath': pathreport.getPath(request, type, entity, True),
       'type': type,
       'entity': entity,
       'downstream': True,
       }))


  @staticmethod
  @staff_member_required
  def viewupstream(request, type, entity):
    return render_to_response('input/path.html', RequestContext(request,{
       'title': _('Supply path report for %(type)s %(entity)s') % {'type':_(type), 'entity':entity},
       'supplypath': pathreport.getPath(request, type, entity, False),
       'type': type,
       'entity': entity,
       'downstream': False,
       }))


@staff_member_required
def location_calendar(request, location):
  # Check to find a location availability calendar
  loc = Location.objects.using(request.database).get(pk=location)
  if loc:
    cal = loc.available
  if cal:
    # Go to the calendar
    return HttpResponseRedirect('%s/admin/input/calendar/%s/' % (request.prefix, iri_to_uri(cal.name)) )
  # Generate a message
  try:
    url = request.META.get('HTTP_REFERER')
    messages.add_message(request, messages.ERROR,
      force_unicode(_('No availability calendar found')))
    return HttpResponseRedirect(url)
  except: raise Http404


class ParameterList(GridReport):
  '''
  A list report to show all configurable parameters.
  '''
  title = _("Parameter List")
  basequeryset = Parameter.objects.all()
  model = Parameter
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('value', title=_('value')),
    GridFieldText('description', title=_('description')),
    GridFieldLastModified('lastmodified'),
    )


class BufferList(GridReport):
  '''
  A list report to show buffers.
  '''
  template = 'input/bufferlist.html'
  title = _("Buffer List")
  basequeryset = Buffer.objects.all()
  model = Buffer
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('location', title=_('location'), field_name='location__name', formatter='location'),
    GridFieldText('item', title=_('item'), field_name='item__name', formatter='item'),
    GridFieldNumber('onhand', title=_('onhand')),
    GridFieldText('owner', title=_('owner'), field_name='owner__name', formatter='buffer'),
    GridFieldText('type', title=_('type')),
    GridFieldNumber('minimum', title=_('minimum')),
    GridFieldText('minimum_calendar', title=_('minimum calendar'), field_name='minimum_calendar__name', formatter='calendar'),
    GridFieldText('producing', title=_('producing'), field_name='producing__name', formatter='operation'),
    GridFieldCurrency('carrying_cost', title=_('carrying cost')),
    GridFieldLastModified('lastmodified'),
    )


class SetupMatrixList(GridReport):
  '''
  A list report to show setup matrices.
  '''
  template = 'input/setupmatrixlist.html'
  title = _("Setup Matrix List")
  basequeryset = SetupMatrix.objects.all()
  model = SetupMatrix
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldLastModified('lastmodified'),
    )


class ResourceList(GridReport):
  '''
  A list report to show resources.
  '''
  template = 'input/resourcelist.html'
  title = _("Resource List")
  basequeryset = Resource.objects.all()
  model = Resource
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('location', title=_('location'), field_name='location__name', formatter='location'),
    GridFieldText('owner', title=_('owner'), field_name='owner__name', formatter='resource'),
    GridFieldText('type', title=_('type')),
    GridFieldNumber('maximum', title=_('maximum')),
    GridFieldText('maximum_calendar', title=_('maximum calendar'), field_name='maximum_calendar__name', formatter='calendar'),
    GridFieldCurrency('cost', title=_('cost')),
    GridFieldNumber('maxearly', title=_('maxearly')),
    GridFieldText('setupmatrix', title=_('setup matrix'), formatter='setupmatrix'),
    GridFieldText('setup', title=_('setup')),
    GridFieldLastModified('lastmodified'),
    )


class LocationList(GridReport):
  '''
  A list report to show locations.
  '''
  template = 'input/locationlist.html'
  title = _("Location List")
  basequeryset = Location.objects.all()
  model = Location
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('available', title=_('available'), field_name='available__name', formatter='calendar'),
    GridFieldText('owner', title=_('owner'), field_name='owner__name', formatter='location'),
    GridFieldLastModified('lastmodified'),
    )


class CustomerList(GridReport):
  '''
  A list report to show customers.
  '''
  template = 'input/customerlist.html'
  title = _("Customer List")
  basequeryset = Customer.objects.all()
  model = Customer
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('owner', title=_('owner'), field_name='owner__name', formatter='customer'),
    GridFieldLastModified('lastmodified'),
    )


class ItemList(GridReport):
  '''
  A list report to show items.
  '''
  template = 'input/itemlist.html'
  title = _("Item List")
  basequeryset = Item.objects.all()
  model = Item
  frozenColumns = 1
  editable = True

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('operation', title=_('operation'), field_name='operation__name'),
    GridFieldText('owner', title=_('owner'), field_name='owner__name'),
    GridFieldCurrency('price', title=_('price')),
    GridFieldLastModified('lastmodified'),
    )


class LoadList(GridReport):
  '''
  A list report to show loads.
  '''
  template = 'input/loadlist.html'
  title = _("Load List")
  basequeryset = Load.objects.all()
  model = Load
  frozenColumns = 1

  rows = (
    GridFieldInteger('id', title=_('identifier'), key=True),
    GridFieldText('operation', title=_('operation'), field_name='operation__name', formatter='operation'),
    GridFieldText('resource', title=_('resource'), field_name='resource__name', formatter='resource'),
    GridFieldNumber('quantity', title=_('quantity')),
    GridFieldDateTime('effective_start', title=_('effective start')),
    GridFieldDateTime('effective_end', title=_('effective end')),
    GridFieldText('name', title=_('name')),
    GridFieldText('alternate', title=_('alternate')),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldText('setup', title=_('setup')),
    GridFieldText('search', title=_('search mode')),
    GridFieldLastModified('lastmodified'),
    )


class FlowList(GridReport):
  '''
  A list report to show flows.
  '''
  template = 'input/flowlist.html'
  title = _("Flow List")
  basequeryset = Flow.objects.all()
  model = Flow
  frozenColumns = 1

  rows = (
    GridFieldInteger('id', title=_('identifier'), key=True),
    GridFieldText('operation', title=_('operation'), field_name='operation__name', formatter='operation'),
    GridFieldText('thebuffer', title=_('buffer'), field_name='thebuffer__name', formatter='buffer'),
    GridFieldText('type', title=_('type')),
    GridFieldNumber('quantity', title=_('quantity')),
    GridFieldDateTime('effective_start', title=_('effective start')),
    GridFieldDateTime('effective_end', title=_('effective end')),
    GridFieldText('name', title=_('name')),
    GridFieldText('alternate', title=_('alternate')),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldText('search', title=_('search mode')),
    GridFieldLastModified('lastmodified'),
    )


class DemandList(GridReport):
  '''
  A list report to show demands.
  '''
  template = 'input/demandlist.html'
  title = _("Demand List")
  basequeryset = Demand.objects.all()
  model = Demand
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('item', title=_('item'), field_name='item__name', formatter='item'),
    GridFieldText('customer', title=_('customer'), field_name='customer__name', formatter='location'),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldDateTime('due', title=_('due')),
    GridFieldNumber('quantity', title=_('quantity')),
    GridFieldText('operation', title=_('delivery operation'), formatter='operation'),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldText('owner', title=_('owner'), formatter='demand'),
    GridFieldNumber('maxlateness', title=_('maximum lateness')),
    GridFieldNumber('minshipment', title=_('minimum shipment')),
    GridFieldLastModified('lastmodified'),
    )


class ForecastList(GridReport):
  '''
  A list report to show forecasts.
  '''
  template = 'input/forecastlist.html'
  title = _("Forecast List")
  basequeryset = Forecast.objects.all()
  model = Forecast
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('item', title=_('item'), field_name='item__name', formatter='item'),
    GridFieldText('customer', title=_('customer'), field_name='customer__name', formatter='customer'),
    GridFieldText('calendar', title=_('calendar'), field_name='calendar__name', formatter='calendar'),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('operation', title=_('operation'), field_name='operation__name', formatter='operation'),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldNumber('maxlateness', title=_('maximum lateness')),
    GridFieldNumber('minshipment', title=_('minimum shipment')),
    GridFieldBool('discrete', title=_('discrete')),
    GridFieldLastModified('lastmodified'),
    )


class CalendarList(GridReport):
  '''
  A list report to show calendars.
  '''
  template = 'input/calendarlist.html'
  title = _("Calendar List")
  basequeryset = Calendar.objects.all()
  model = Calendar
  frozenColumns = 1
  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('type', title=_('type')),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldNumber('defaultvalue', title=_('default value')),
    GridFieldNumber('currentvalue', title=_('current value'), sortable=False),
    GridFieldLastModified('lastmodified'),
    )


class CalendarBucketList(GridReport):
  '''
  A list report to show calendar buckets.
  '''
  template = 'input/calendarbucketlist.html'
  title = _("Calendar Bucket List")
  basequeryset = CalendarBucket.objects.all()
  model = CalendarBucket
  frozenColumns = 1
  rows = (
    GridFieldNumber('id', title=_('identifier'), key=True),
    GridFieldText('calendar', title=_('calendar'), field_name='calendar__name', formatter='calendar'),
    GridFieldDateTime('startdate', title=_('start date')),
    GridFieldDateTime('enddate', title=_('end date')),
    GridFieldNumber('value', title=_('value')),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldText('name', title=_('name')),
    GridFieldLastModified('lastmodified'),
    )


class OperationList(GridReport):
  '''
  A list report to show operations.
  '''
  template = 'input/operationlist.html'
  title = _("Operation List")
  basequeryset = Operation.objects.all()
  model = Operation
  frozenColumns = 1

  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldText('category', title=_('category')),
    GridFieldText('subcategory', title=_('subcategory')),
    GridFieldText('type', title=_('type')),
    GridFieldText('location', title=_('location'), field_name='location__name', formatter='location'),
    GridFieldNumber('duration', title=_('duration')),
    GridFieldNumber('duration_per', title=_('duration_per')),
    GridFieldNumber('fence', title=_('fence')),
    GridFieldNumber('pretime', title=_('pre-op time')),
    GridFieldNumber('posttime', title=_('post-op time')),
    GridFieldNumber('sizeminimum', title=_('size minimum')),
    GridFieldNumber('sizemultiple', title=_('size multiple')),
    GridFieldNumber('sizemaximum', title=_('size maximum')),
    GridFieldCurrency('cost', title=_('cost')),
    GridFieldText('search', title=_('search mode')),
    GridFieldLastModified('lastmodified'),
    )


class SubOperationList(GridReport):
  '''
  A list report to show suboperations.
  '''
  template = 'input/suboperationlist.html'
  title = _("Suboperation List")
  basequeryset = SubOperation.objects.all()
  model = SubOperation
  frozenColumns = 1

  rows = (
    GridFieldNumber('id', title=_('identifier'), key=True),
    GridFieldText('operation', title=_('operation'), field_name='operation__name', formatter='operation'),
    GridFieldText('suboperation', title=_('suboperation'), field_name='suboperation__name', formatter='operation'),
    GridFieldNumber('priority', title=_('priority')),
    GridFieldDateTime('effective_start', title=_('effective start')),
    GridFieldDateTime('effective_end', title=_('effective end')),
    GridFieldLastModified('lastmodified'),
    )


class OperationPlanList(GridReport):
  '''
  A list report to show operationplans.
  '''
  template = 'input/operationplanlist.html'
  title = _("Operationplan List")
  basequeryset = OperationPlan.objects.all()
  model = OperationPlan
  frozenColumns = 1

  rows = (
    GridFieldInteger('id', title=_('identifier'), key=True),
    GridFieldText('operation', title=_('operation'), field_name='operation__name', formatter='operation'),
    GridFieldDateTime('startdate', title=_('start date')),
    GridFieldDateTime('enddate', title=_('end date')),
    GridFieldNumber('quantity', title=_('quantity')),
    GridFieldBool('locked', title=_('locked')),
    GridFieldInteger('owner', title=_('owner')),
    GridFieldLastModified('lastmodified'),
    )


class BucketList(GridReport):
  '''
  A list report to show dates.
  '''
  title = _("Bucket List")
  basequeryset = Bucket.objects.all()
  model = Bucket
  frozenColumns = 1
  rows = (
    GridFieldText('name', title=_('name'), key=True),
    GridFieldText('description', title=_('description')),
    GridFieldLastModified('lastmodified'),
    )


class BucketDetailList(GridReport):
  '''
  A list report to show dates.
  '''
  title = _("Bucket Detail List")
  basequeryset = BucketDetail.objects.all()
  model = BucketDetail
  frozenColumns = 1
  rows = (
    GridFieldNumber('id', title=_('identifier'), key=True),
    GridFieldText('bucket', title=_('bucket'), field_name='bucket__name'),
    GridFieldDateTime('startdate', title=_('start date')),
    GridFieldDateTime('enddate', title=_('end date')),
    GridFieldLastModified('lastmodified'),
    )
