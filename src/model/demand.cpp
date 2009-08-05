/***************************************************************************
  file : $URL$
  version : $LastChangedRevision$  $LastChangedBy$
  date : $LastChangedDate$
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 * Copyright (C) 2007 by Johan De Taeye                                    *
 *                                                                         *
 * This library is free software; you can redistribute it and/or modify it *
 * under the terms of the GNU Lesser General Public License as published   *
 * by the Free Software Foundation; either version 2.1 of the License, or  *
 * (at your option) any later version.                                     *
 *                                                                         *
 * This library is distributed in the hope that it will be useful,         *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of          *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser *
 * General Public License for more details.                                *
 *                                                                         *
 * You should have received a copy of the GNU Lesser General Public        *
 * License along with this library; if not, write to the Free Software     *
 * Foundation Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA *
 *                                                                         *
 ***************************************************************************/

#define FREPPLE_CORE
#include "frepple/model.h"

namespace frepple
{

template<class Demand> DECLARE_EXPORT Tree utils::HasName<Demand>::st;


DECLARE_EXPORT void Demand::setQuantity(double f)
{
  // Reject negative quantities, and no-change updates
  double delta(f - qty);
  if (f < 0.0 || fabs(delta)<ROUNDING_ERROR) return;

  // Update the quantity
  qty = f;
  setChanged();
}


DECLARE_EXPORT void Demand::deleteOperationPlans (bool deleteLockedOpplans)
{
  // Delete all opplans
  for (OperationPlan_list::iterator i = deli.begin(); i!=deli.end(); )
    if (deleteLockedOpplans || !(*i)->getLocked())
    {
      // Setting the demand pointer to NULL is required to prevent the
      // deletion of the operationplan calling the function removeDelivery.
      // We can't use the regular method setDemand() to do this!
      (*i)->dmd = NULL;
      delete *i;
      // Remove from the list - while trying to maintain a valid iterator to
      // the next element.
      OperationPlan_list::iterator todelete = i;
      ++i;
      deli.erase(todelete);
    }
    else ++i;

  // Mark the demand as being changed, so the problems can be redetected
  setChanged();
}


DECLARE_EXPORT void Demand::removeDelivery(OperationPlan * o)
{
  // Valid opplan check
  if (!o) return;

  // See if the demand field on the operationplan points to this demand
  if (o->dmd != this)
    throw LogicException("Delivery operationplan incorrectly registered");

  // Remove the reference on the operationplan
  o->dmd = NULL;  // Required to avoid endless loop
  o->setDemand(NULL);

  // Find in the list of deliveries
  OperationPlan_list::iterator j = deli.begin();
  while (j!=deli.end() && *j!=o) ++j;

  // Check that the operation is found
  // It is possible it is not found! This happens if e.g. an operationplan
  // is created but destroyed again before it is initialized.
  if (j!=deli.end())
  {
    // Remove from the list
    deli.erase(j);
    // Mark the demand as being changed, so the problems can be redetected
    setChanged();
  }
}


DECLARE_EXPORT const Demand::OperationPlan_list& Demand::getDelivery() const
{
  // We need to check the sorting order of the list first! It could be disturbed
  // when operationplans are being moved around.
  // The sorting routine isn't very efficient, but should suffice since the
  // list of delivery operationplans is short and isn't expected to be
  // disturbed very often.
  for (bool swapped(!deli.empty()); swapped; swapped=false)
  {
    OperationPlan_list::iterator j = const_cast<Demand*>(this)->deli.begin();
    ++j;
    for (OperationPlan_list::iterator i =
          const_cast<Demand*>(this)->deli.begin();
        j!=const_cast<Demand*>(this)->deli.end(); ++j)
    {
      if ((*i)->getDates().getEnd() < (*j)->getDates().getEnd())
      {
        // Oh yes, the ordering was disrupted indeed...
        iter_swap(i,j);
        // The Borland compiler doesn't understand that this variable is used.
        // It gives a incorrect warning message...
        swapped = true;
        break;
      }
      ++i;
    }
  }

  return deli;
}

    
DECLARE_EXPORT OperationPlan* Demand::getLatestDelivery() const
{
  const Demand::OperationPlan_list& l = getDelivery();
  return l.empty() ? NULL : *(l.begin());
}


DECLARE_EXPORT OperationPlan* Demand::getEarliestDelivery() const
{
  const Demand::OperationPlan_list& l = getDelivery();
  OperationPlan *last = NULL;
  for (Demand::OperationPlan_list::const_iterator i = l.begin(); i!=l.end(); ++i)
    last = *i;
  return last;
}


DECLARE_EXPORT void Demand::addDelivery (OperationPlan * o)
{
  // Dummy call to this function
  if (!o) return;

  // Check if it is already in the list.
  // If it is, simply exit the function. No need to give a warning message
  // since it's harmless.
  for (OperationPlan_list::iterator i = deli.begin(); i!=deli.end(); ++i)
    if (*i == o) return;

  // Add to the list of delivery operationplans. The insertion is such
  // that the delivery list is sorted in terms of descending end time.
  // i.e. the opplan with the latest end date is on the front of the list.
  // Note: We're forcing resorting the deliveries with the getDelivery()
  // method. Operation plans dates could have changed, thus disturbing the
  // original order.
  getDelivery();
  OperationPlan_list::iterator j = deli.begin();
  while (j!=deli.end() && (*j)->getDates().getEnd()>o->getDates().getEnd()) ++j;
  deli.insert(j, o);

  // Mark the demand as being changed, so the problems can be redetected
  setChanged();

  // Create link between operationplan and demand
  o->setDemand(this);

  // Check validity of operation being used
  Operation* tmpOper = getDeliveryOperation();
  if (tmpOper && tmpOper != o->getOperation())
    logger << "Warning: Delivery Operation '" << o->getOperation()
    << "' different than expected '" << tmpOper
    << "' for demand '" << this << "'" << endl;
}


DECLARE_EXPORT Operation* Demand::getDeliveryOperation() const
{
  // Operation can be specified on the demand itself,
  if (oper) return oper;
  // ... or on the item,
  if (it) return it->getOperation();
  // ... or it doesn't exist at all
  return NULL;
}


DECLARE_EXPORT double Demand::getPlannedQuantity() const
{
  double delivered(0.0);
  for (OperationPlan_list::const_iterator i=deli.begin(); i!=deli.end(); ++i)
    delivered += (*i)->getQuantity();
  return delivered;
}


DECLARE_EXPORT void Demand::writeElement(XMLOutput *o, const Keyword& tag, mode m) const
{
  // Writing a reference
  if (m == REFERENCE)
  {
    o->writeElement(tag, Tags::tag_name, getName());
    return;
  }

  // Write the complete object
  if (m != NOHEADER) o->BeginObject(tag, Tags::tag_name, getName());

  // Write the fields
  HasDescription::writeElement(o, tag);
  HasHierarchy<Demand>::writeElement(o, tag);
  o->writeElement(Tags::tag_operation, oper);
  o->writeElement(Tags::tag_customer, cust);
  Plannable::writeElement(o, tag);

  o->writeElement(Tags::tag_quantity, qty);
  o->writeElement(Tags::tag_item, it);
  o->writeElement(Tags::tag_due, dueDate);
  if (getPriority()) o->writeElement(Tags::tag_priority, getPriority());
  if (getMaxLateness() != TimePeriod::MAX)
    o->writeElement(Tags::tag_maxlateness, getMaxLateness());
  if (getMinShipment())
    o->writeElement(Tags::tag_minshipment, getMinShipment());

  // Write extra plan information
  if ((o->getContentType() == XMLOutput::PLAN
      || o->getContentType() == XMLOutput::PLANDETAIL) && !deli.empty())
  {
    o->BeginObject(Tags::tag_operationplans);
    for (OperationPlan_list::const_iterator i=deli.begin(); i!=deli.end(); ++i)
      o->writeElement(Tags::tag_operationplan, *i, FULL);
    o->EndObject(Tags::tag_operationplans);
  }
  o->EndObject(tag);
}


DECLARE_EXPORT void Demand::beginElement(XMLInput& pIn, const Attribute& pAttr)
{
  if (pAttr.isA (Tags::tag_item))
    pIn.readto( Item::reader(Item::metadata,pIn.getAttributes()) );
  else if (pAttr.isA (Tags::tag_operation))
    pIn.readto( Operation::reader(Operation::metadata,pIn.getAttributes()) );
  else if (pAttr.isA (Tags::tag_customer))
    pIn.readto( Customer::reader(Customer::metadata,pIn.getAttributes()) );
  else if (pAttr.isA(Tags::tag_operationplan))
    pIn.readto(OperationPlan::createOperationPlan(OperationPlan::metadata,pIn.getAttributes()));
  else
    HasHierarchy<Demand>::beginElement(pIn, pAttr);
}


DECLARE_EXPORT void Demand::endElement(XMLInput& pIn, const Attribute& pAttr, const DataElement& pElement)
{
  if (pAttr.isA (Tags::tag_quantity))
    setQuantity (pElement.getDouble());
  else if (pAttr.isA (Tags::tag_priority))
    setPriority (pElement.getInt());
  else if (pAttr.isA (Tags::tag_due))
    setDue(pElement.getDate());
  else if (pAttr.isA (Tags::tag_operation))
  {
    Operation *o = dynamic_cast<Operation*>(pIn.getPreviousObject());
    if (o) setOperation(o);
    else throw LogicException("Incorrect object type during read operation");
  }
  else if (pAttr.isA (Tags::tag_customer))
  {
    Customer *c = dynamic_cast<Customer*>(pIn.getPreviousObject());
    if (c) setCustomer(c);
    else throw LogicException("Incorrect object type during read operation");
  }
  else if (pAttr.isA (Tags::tag_item))
  {
    Item *i = dynamic_cast<Item*>(pIn.getPreviousObject());
    if (i) setItem(i);
    else throw LogicException("Incorrect object type during read operation");
  }
  else if (pAttr.isA (Tags::tag_maxlateness))
    setMaxLateness(pElement.getTimeperiod());
  else if (pAttr.isA (Tags::tag_minshipment))
    setMinShipment(pElement.getDouble());
  else if (pAttr.isA(Tags::tag_operationplan))
  {
    OperationPlan* opplan
      = dynamic_cast<OperationPlan*>(pIn.getPreviousObject());
    if (opplan) addDelivery(opplan);
    else throw LogicException("Incorrect object type during read operation");
  }
  else
  {
    Plannable::endElement(pIn, pAttr, pElement);
    HasDescription::endElement(pIn, pAttr, pElement);
    HasHierarchy<Demand>::endElement (pIn, pAttr, pElement);
  }
}


DECLARE_EXPORT PyObject* PythonDemand::getattro(const Attribute& attr)
{
  if (!obj) return Py_BuildValue("");
  if (attr.isA(Tags::tag_name))
    return PythonObject(obj->getName());
  if (attr.isA(Tags::tag_quantity))
    return PythonObject(obj->getQuantity());
  if (attr.isA(Tags::tag_due))
    return PythonObject(obj->getDue());
  if (attr.isA(Tags::tag_priority))
    return PythonObject(obj->getPriority());
  if (attr.isA(Tags::tag_owner))
    return PythonObject(obj->getOwner());
  if (attr.isA(Tags::tag_item))
    return PythonObject(obj->getItem());
  if (attr.isA(Tags::tag_customer))
    return PythonObject(obj->getCustomer());
  if (attr.isA(Tags::tag_operation))
    return PythonObject(obj->getOperation());
  if (attr.isA(Tags::tag_description))
    return PythonObject(obj->getDescription());
  if (attr.isA(Tags::tag_category))
    return PythonObject(obj->getCategory());
  if (attr.isA(Tags::tag_subcategory))
    return PythonObject(obj->getSubCategory());
  if (attr.isA(Tags::tag_minshipment))
    return PythonObject(obj->getMinShipment());
  if (attr.isA(Tags::tag_maxlateness))
    return PythonObject(obj->getMaxLateness());
  if (attr.isA(Tags::tag_hidden))
    return PythonObject(obj->getHidden());
  if (attr.isA(Tags::tag_operationplans))
    return new PythonDemandPlanIterator(obj);
  if (attr.isA(Tags::tag_pegging))
    return new PythonPeggingIterator(obj);
  return NULL;
}


DECLARE_EXPORT int PythonDemand::setattro(const Attribute& attr, const PythonObject& field)
{
  if (attr.isA(Tags::tag_name))
    obj->setName(field.getString());
  else if (attr.isA(Tags::tag_priority))
    obj->setPriority(field.getInt());
  else if (attr.isA(Tags::tag_quantity))
    obj->setQuantity(field.getDouble());
  else if (attr.isA(Tags::tag_due))
    obj->setDue(field.getDate());
  else if (attr.isA(Tags::tag_item))
  {
    if (!field.check(PythonItem::getType())) 
    {
      PyErr_SetString(PythonDataException, "demand item must be of type item");
      return -1;
    }
    Item* y = static_cast<PythonItem*>(static_cast<PyObject*>(field))->obj;
    obj->setItem(y);
  }
  else if (attr.isA(Tags::tag_customer))
  {
    if (!field.check(PythonCustomer::getType())) 
    {
      PyErr_SetString(PythonDataException, "demand customer must be of type customer");
      return -1;
    }
    Customer* y = static_cast<PythonCustomer*>(static_cast<PyObject*>(field))->obj;
    obj->setCustomer(y);
  }
  else if (attr.isA(Tags::tag_description))
    obj->setDescription(field.getString());
  else if (attr.isA(Tags::tag_category))
    obj->setCategory(field.getString());
  else if (attr.isA(Tags::tag_subcategory))
    obj->setSubCategory(field.getString());
  else if (attr.isA(Tags::tag_minshipment))
    obj->setMinShipment(field.getDouble());
  else if (attr.isA(Tags::tag_maxlateness))
    obj->setMaxLateness(field.getTimeperiod());
  else if (attr.isA(Tags::tag_owner))
  {
    if (!field.check(PythonDemand::getType()))
    {
      PyErr_SetString(PythonDataException, "demand owner must be of type demand");
      return -1;
    }
    Demand* y = static_cast<PythonDemand*>(static_cast<PyObject*>(field))->obj;
    obj->setOwner(y);
  }
  else if (attr.isA(Tags::tag_operation))
  {
    if (!field.check(PythonOperation::getType()))
    {
      PyErr_SetString(PythonDataException, "demand operation must be of type operation");
      return -1;
    }
    Operation* y = static_cast<PythonOperation*>(static_cast<PyObject*>(field))->obj;
    obj->setOperation(y);
  }
  else if (attr.isA(Tags::tag_hidden))
    obj->setHidden(field.getBool());
  else
    return -1;  // Error
  return 0;  // OK
}


DECLARE_EXPORT PyObject* PythonDemandDefault::getattro(const Attribute& attr)
{
  return PythonDemand(obj).getattro(attr); 
}


DECLARE_EXPORT int PythonDemandDefault::setattro(const Attribute& attr, const PythonObject& field)
{
  return PythonDemand(obj).setattro(attr, field);
}


int PythonDemandPlanIterator::initialize(PyObject* m)
{
  // Initialize the type
  PythonType& x = PythonExtension<PythonDemandPlanIterator>::getType();
  x.setName("demandplanIterator");
  x.setDoc("frePPLe iterator for demand delivery operationplans");
  x.supportiter();
  return x.typeReady(m);
}


PyObject* PythonDemandPlanIterator::iternext()
{  
  if (i == dem->getDelivery().end()) return NULL;
  return new PythonOperationPlan(const_cast<OperationPlan*>(&**(i++)));
}

} // end namespace
