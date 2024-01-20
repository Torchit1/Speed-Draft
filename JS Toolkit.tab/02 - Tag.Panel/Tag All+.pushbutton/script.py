# -*- coding: utf-8 -*-

from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script
from collections import defaultdict
import config, clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

doc = revit.doc
output = script.get_output()
element_cache = {}

ignored_tag_types = set()


def is_tag_type_loaded(doc, built_in_category):
    collector = FilteredElementCollector(doc)
    collector.WherePasses(ElementClassFilter(ElementType))
    collector.WherePasses(ElementCategoryFilter(built_in_category))
    return any(collector)


def is_element_visible_in_view(doc, view, element):
    category_id = element.Category.Id
    collector = FilteredElementCollector(doc, view.Id).OfCategoryId(category_id).WhereElementIsNotElementType()
    return any(e.Id == element.Id for e in collector)


def get_projected_center_point(element):
    bbox = element.get_BoundingBox(None)
    if not bbox:
        return None
    center = bbox.Min + 0.5 * (bbox.Max - bbox.Min)
    return center


def get_revit_version(app):
    return int(app.VersionNumber)

def tag_elements_in_view(doc, view, elements, progress_bar):
    revit_version = get_revit_version(doc.Application)
    print("Running on Revit version: {}".format(revit_version))  # Output the Revit version

    toggle_settings = config.load_toggle_settings()
    existing_tags = FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)

    already_tagged_element_ids = set()
    for tag in existing_tags:
        try:
            if revit_version <= 2021:
                # Revit 2021 and earlier
                tagged_element = tag.GetTaggedLocalElement()
                if tagged_element:
                    # Ensure we get the ElementId, then its IntegerValue
                    tagged_id = tagged_element.Id.IntegerValue
                    already_tagged_element_ids.add(tagged_id)
            else:
                # Revit 2023 and later
                tagged_elements = tag.GetTaggedLocalElements()
                for te in tagged_elements:
                    # Here too, make sure to use ElementId's IntegerValue
                    already_tagged_element_ids.add(te.Id.IntegerValue)
        except Exception as e:
            print("Error processing tag: {}".format(str(e)))

    for idx, element in enumerate(elements):
        try:
            progress_bar.update_progress(idx, len(elements))

            if element.Id.IntegerValue in already_tagged_element_ids:
                continue

            if toggle_settings['toggle_visibility'] and not is_element_visible_in_view(doc, view, element):
                continue

            if not is_tag_type_loaded(doc, element.Category.Id) and element.Category.Id not in ignored_tag_types:
                user_choice = forms.alert(
                    'No tag type loaded for category: {}\nDo you want to continue anyway?'.format(element.Category.Name),
                    yes=True, no=True, exitscript=True)
                if user_choice == 'No':
                    return  # Exit the function if user chooses to cancel
                ignored_tag_types.add(element.Category.Id)

            center_point = get_projected_center_point(element)
            if center_point is None:
                continue

            if element.Category.Name == "Windows" and view.ViewType == ViewType.FloorPlan and toggle_settings['tag_windows_in_plan']:
                tag = IndependentTag.Create(doc, view.Id, Reference(element), True, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, center_point)
            else:
                tag = IndependentTag.Create(doc, view.Id, Reference(element), False, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, center_point)

            if toggle_settings['check_blank_tag'] and not tag.TagText.strip():
                doc.Delete(tag.Id)

        except Exception as e:
            print("Error processing element ID {}: {}".format(element.Id, str(e)))
            continue



def select_categories(doc):
    categories = doc.Settings.Categories
    specific_categories = config.load_configs()
    category_names = [cat.Name for cat in categories if cat.Name in specific_categories and cat.AllowsBoundParameters]
    
    try:
        selected_category_names = forms.SelectFromList.show(category_names,
                                                            multiselect=True,
                                                            title='Select Categories to Tag',
                                                            button_name='Select')
        if selected_category_names is None:
            raise SystemExit
        selected_categories = [categories.get_Item(name) for name in selected_category_names]
        print("Selected Categories: " + ", ".join(selected_category_names))  # Debugging output
        return selected_categories
    except Exception as e:
        print("Error in select_categories: " + str(e))
        raise



def select_elements(doc, selected_categories):
    selected_elements = []
    try:
        for category in selected_categories:
            elements_collector = FilteredElementCollector(doc).OfCategoryId(category.Id).WhereElementIsNotElementType()
            category_elements = [el for el in elements_collector]
            element_cache[category.Id] = category_elements
            selected_elements.extend(category_elements)
            element_ids = [str(el.Id) for el in category_elements]
            print("Collected elements for category {}: {}".format(category.Name, ", ".join(element_ids)))  # Log element IDs
        return selected_elements
    except Exception as e:
        print("Error in select_elements: " + str(e))
        raise



def select_views(doc):
    all_views = FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements()
    target_view_types = [ViewType.FloorPlan, ViewType.Elevation, ViewType.Section]
    available_views = [v for v in all_views if v.ViewType in target_view_types and not v.IsTemplate]
    view_names = sorted([v.Name for v in available_views])
    
    try:
        selected_view_names = forms.SelectFromList.show(view_names,
                                                        multiselect=True,
                                                        title='Select Views',
                                                        button_name='Select')
        if selected_view_names is None:
            raise SystemExit
        selected_views = [v for v in available_views if v.Name in selected_view_names]
        print("Selected Views: " + ", ".join(selected_view_names))  # Debugging output
        return selected_views
    except Exception as e:
        print("Error in select_views: " + str(e))
        raise


def tag_elements_in_selected_views(doc, selected_views, selected_elements):
    tagged_views_info = defaultdict(list)
    with forms.ProgressBar(title='Tagging Elements... By Jesse Symons', maximum=len(selected_elements)) as pb:
        t = Transaction(doc, 'Tag Selected Elements in All Views')
        t.Start()
        try:
            for view in selected_views:
                tag_elements_in_view(doc, view, selected_elements, pb)
            t.Commit()
        except Exception:
            t.RollBack()
            raise


try:
    selected_categories = select_categories(doc)
    selected_elements = select_elements(doc, selected_categories)
    selected_views = select_views(doc)
    if selected_elements and selected_views:
        tag_elements_in_selected_views(doc, selected_views, selected_elements)
except SystemExit:
    pass
except Exception as e:
    print("General Error: " + str(e))

