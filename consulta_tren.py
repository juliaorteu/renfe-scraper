#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 Renfe Train Scraper
---------------------------------
This scraper allows you to search for train tickets between any stations,
for any day within the next week, and filter by train type and departure time.
Author: Julia Orteu
Copyright: © 2025 Julia Orteu. All rights reserved.
License: MIT License
Repository: https://github.com/juliaorteu/renfe-scraper
"""


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from datetime import datetime, timedelta
import time
import re
import logging
import argparse
from typing import List, Dict, Optional, Tuple


class TrainType:
    """Supported train types"""
    AVE = 'AVE'
    AVANT = 'AVANT'
    MD = 'MD'  # Media Distancia
    ALL = 'ALL'


class RenfeError(Exception):
    """Custom exception for Renfe scraper errors"""
    pass


class RenfeSeleniumScraper:
    def __init__(self, 
                 origin: str = "Girona",
                 destination: str = "Barcelona-Sants",
                 days_from_now: int = 1,
                 train_types: List[str] = None,
                 time_filter: Optional[Tuple[str, str]] = None,
                 verbose: bool = True):
        """
        Initialize the scraper with customizable parameters.
        
        Args:
            origin: Origin station name
            destination: Destination station name  
            days_from_now: Days from today (0-15)
            train_types: List of train types to include (default: [AVE, AVANT])
            time_filter: Optional tuple of (filter_type, time_value) where filter_type is 'before' or 'after'
            verbose: Whether to print detailed logs
        """
        self.origin = origin
        self.destination = destination
        self.verbose = verbose
        
        # Configure logging based on verbosity
        self._setup_logging()
        
        # Validate days_from_now
        if not 0 <= days_from_now <= 15:
            raise ValueError("days_from_now must be between 0 and 15")
        
        # Calculate the search date
        target_date = datetime.now() + timedelta(days=days_from_now)
        self.day = target_date.day
        self.month = target_date.month
        self.year = target_date.year
        self.date_str = target_date.strftime("%d/%m/%Y")
        
        # Configure train types to search for
        self.train_types = train_types if train_types else [TrainType.AVE, TrainType.AVANT]
        if TrainType.ALL in self.train_types:
            self.train_types = [TrainType.AVE, TrainType.AVANT, TrainType.MD]
        
        # Set time filter
        self.time_filter = time_filter
        
        # Configure WebDriver
        self._setup_driver()
    
    def _setup_logging(self):
        """Configure logging based on verbosity setting"""
        # Clear any existing handlers
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        
        # Set up logging
        log_level = logging.INFO if self.verbose else logging.WARNING
        handlers = [logging.FileHandler('renfe_scraper.log')]
        
        if self.verbose:
            handlers.append(logging.StreamHandler())
            
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Logging initialized")
        
    def _setup_driver(self):
        """Configure Chrome WebDriver options"""
        self.options = webdriver.ChromeOptions()
        self.options.add_argument("--start-maximized")
        self.options.add_argument("--disable-notifications")
        self.options.add_argument("--disable-popup-blocking")
        self.options.add_argument("--disable-dev-shm-usage")  # Help with memory issues
        self.options.add_argument("--no-sandbox")  # Help with permissions issues
        self.options.add_experimental_option("excludeSwitches", ["enable-logging"])
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.options.add_experimental_option('useAutomationExtension', False)
        self.options.add_argument("--headless")  # Run Chrome in headless mode (no GUI)

        
        self.driver = webdriver.Chrome(options=self.options)
        self.wait = WebDriverWait(self.driver, 20)
        
    def _accept_cookies(self):
        """Accept cookies if the banner appears"""
        try:
            accept_btn = self.wait.until(
                EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
            )
            accept_btn.click()
            self.logger.info("Cookies accepted")
            time.sleep(1)
        except TimeoutException:
            self.logger.info("No cookie banner found")
    
    def _fill_station(self, field_id: str, station_name: str, field_type: str):
        """Fill a station field (origin or destination)"""
        try:
            # Wait for field to be clickable
            field = self.wait.until(EC.element_to_be_clickable((By.ID, field_id)))
            
            # Clear field with multiple methods to ensure it's empty
            field.click()
            field.clear()
            field.send_keys(Keys.CONTROL + "a")
            field.send_keys(Keys.DELETE)
            time.sleep(0.5)
            
            # Type station name
            field.send_keys(station_name)
            time.sleep(2)  # Increased wait time for autocomplete
            
            # Try to select from autocomplete
            try:
                suggestions = self.wait.until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, "//div[contains(@class, 'autocomplete')]//li")
                    )
                )
                
                # Special handling for common stations
                if field_type == "destination":
                    for suggestion in suggestions:
                        if station_name.upper() in suggestion.text.upper():
                            suggestion.click()
                            self.logger.info(f"{field_type.capitalize()} selected: {station_name}")
                            return
                
                # Default to first suggestion if no specific match found
                if suggestions:
                    suggestions[0].click()
                    self.logger.info(f"{field_type.capitalize()} selected: {station_name}")
                
            except TimeoutException:
                # Fallback to keyboard navigation
                field.send_keys(Keys.ARROW_DOWN, Keys.ENTER)
                self.logger.info(f"{field_type.capitalize()} selected via keyboard")
            
            time.sleep(1)
            
        except Exception as e:
            raise RenfeError(f"Error filling {field_type}: {e}")
    
    def _select_date(self):
        """Select the desired date from the calendar"""
        try:
            # Open calendar
            date_input = self.driver.find_element(By.ID, "first-input")
            date_input.click()
            time.sleep(2)
            
            # Select one-way trip
            solo_ida_label = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//label[@for='trip-go']"))
            )
            solo_ida_label.click()
            self.logger.info("One-way trip selected")
            time.sleep(1)
            
            # Select the date
            day_selector = f"//div[contains(@class, 'lightpick__day') and text()='{self.day}' and not(contains(@class, 'is-previous-month')) and not(contains(@class, 'is-next-month'))]"
            day_element = self.wait.until(EC.element_to_be_clickable((By.XPATH, day_selector)))
            day_element.click()
            self.logger.info(f"Date {self.date_str} selected")
            time.sleep(1)
            
            # Click accept button if present
            try:
                accept_btn = self.wait.until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "#datepickerv2 > section > div.lightpick__footer-buttons > button.lightpick__apply-action-sub")
                    )
                )
                self.driver.execute_script("arguments[0].click();", accept_btn)
                self.logger.info("Calendar accept button clicked")
            except TimeoutException:
                pass  # Accept button not always present
            
            time.sleep(2)
            
        except Exception as e:
            raise RenfeError(f"Error selecting date: {e}")
    
    def _search_trips(self):
        """Execute the search for trips"""
        try:
            # Scroll to top to ensure visibility
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)
            
            # Find and click search button
            search_btn = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[@type='submit' and contains(@class,'mdc-button') and contains(@class,'rf-button--primary')]")
                )
            )
            self.driver.execute_script("arguments[0].click();", search_btn)
            self.logger.info("Search initiated")
            
            # Wait for results to load
            time.sleep(15)  # Allow time for results to load
            
        except Exception as e:
            raise RenfeError(f"Error searching for trips: {e}")
    
    def _extract_trip_info(self, trip_element) -> Dict[str, str]:
        """Extract information from a single trip element"""
        trip_info = {}
        
        try:
            # Extract train type from image alt text
            img_elem = trip_element.find_element(By.CSS_SELECTOR, "img.img-fluid")
            alt_text = img_elem.get_attribute("alt")
            
            if "Tipo de tren" in alt_text:
                tipo_match = re.search(r'Tipo de tren (\w+)', alt_text)
                if tipo_match:
                    trip_info['tipo'] = tipo_match.group(1)
                else:
                    trip_info['tipo'] = alt_text.replace('Tipo de tren ', '').strip()

        except:
            trip_info['tipo'] = 'N/A'
        
        try:
            # Extract departure and arrival times
            horas = trip_element.find_elements(By.TAG_NAME, "h5")
            if len(horas) >= 2:
                trip_info['salida'] = horas[0].text.replace("h", "").strip()
                trip_info['llegada'] = horas[1].text.replace("h", "").strip()
        except:
            pass
        
        try:
            # Extract duration
            duracion_elem = trip_element.find_element(By.CSS_SELECTOR, "span.text-number")
            trip_info['duracion'] = duracion_elem.text.strip()
        except:
            pass
        
        try:
            # Extract price
            precio_elem = trip_element.find_element(By.CSS_SELECTOR, "span.precio-final")
            precio_text = precio_elem.text
            trip_info['precio'] = precio_text.split("desde")[-1].strip()
        except:
            pass

        try:
            full_train_button = trip_element.find_element(By.XPATH, ".//div[@id='boton-style' and contains(., 'Tren Completo')]")
            trip_info["completo"] = True
        except:
            trip_info["completo"] = False
        
        return trip_info
    
    def _filter_by_time(self, trips: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Filter trips based on departure time"""
        if not self.time_filter:
            return trips
            
        filter_type, time_value = self.time_filter
        self.logger.info(f"Filtering trips {filter_type} {time_value}")
        
        # Convert time_value to minutes since midnight for comparison
        filter_hour, filter_minute = map(int, time_value.split(':'))
        filter_minutes = filter_hour * 60 + filter_minute
        
        filtered_trips = []
        for trip in trips:
            departure_time = trip.get('salida', '')
            if not departure_time:
                continue
                
            # Convert departure time to minutes for comparison
            try:
                # Handle different time formats (08:30 or 8:30)
                parts = departure_time.split(':')
                if len(parts) == 2:
                    hour, minute = map(int, parts)
                else:
                    # Try to handle format like "8.30"
                    parts = departure_time.replace('.', ':').split(':')
                    hour, minute = map(int, parts)
                
                departure_minutes = hour * 60 + minute
                
                # Apply filter
                if filter_type == 'before' and departure_minutes <= filter_minutes:
                    filtered_trips.append(trip)
                elif filter_type == 'after' and departure_minutes >= filter_minutes:
                    filtered_trips.append(trip)
            except ValueError:
                # If time parsing fails, include the trip to be safe
                filtered_trips.append(trip)
                self.logger.warning(f"Could not parse departure time: {departure_time}")
                
        return filtered_trips
    
    def _extract_results(self) -> List[Dict[str, str]]:
        """Extract all trip results from the page"""
        trips = []
        
        try:
            # Find all trip elements
            trip_elements = self.driver.find_elements(By.CLASS_NAME, "selectedTren")
            self.logger.info(f"Found {len(trip_elements)} total trips")
            
            for trip_element in trip_elements:
                trip_info = self._extract_trip_info(trip_element)
                
                # Filter by train type
                trip_type = trip_info.get('tipo', 'N/A')
                if (trip_type in self.train_types or 
                    (trip_type == 'N/A' and 'ALL' in self.train_types)):
                    trips.append(trip_info)
            
            # Apply time filtering if specified
            if self.time_filter:
                trips = self._filter_by_time(trips)
                    
            return trips
            
        except Exception as e:
            self.logger.error(f"Error extracting results: {e}")
            return []
    
    def _save_screenshot(self, filename: str = "renfe_results.png"):
        """Save a screenshot of the current page"""
        try:
            self.driver.save_screenshot(filename)
            self.logger.info(f"Screenshot saved to {filename}")
        except Exception as e:
            self.logger.error(f"Error saving screenshot: {e}")
    
    def run(self) -> List[Dict[str, str]]:
        """Execute the scraping process and return results"""
        try:
            self.logger.info(f"Searching tickets from {self.origin} to {self.destination} for {self.date_str}")
            if self.time_filter:
                filter_type, time_value = self.time_filter
                self.logger.info(f"Time filter: {filter_type} {time_value}")
            self.logger.info(f"Train types: {', '.join(self.train_types)}")
            
            # Open Renfe website
            self.driver.get("https://www.renfe.com/es/es")
            time.sleep(3)  # Give the page time to load properly
            
            # Accept cookies
            self._accept_cookies()
            
            # Fill origin with retry mechanism
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    self._fill_station("origin", self.origin, "origin")
                    break
                except Exception as e:
                    if attempt < max_attempts - 1:
                        self.logger.warning(f"Attempt {attempt + 1} failed to fill origin, retrying...")
                        time.sleep(2)
                        self.driver.refresh()
                        time.sleep(3)
                        self._accept_cookies()
                    else:
                        raise e
            
            # Fill destination with retry mechanism
            for attempt in range(max_attempts):
                try:
                    self._fill_station("destination", self.destination, "destination")
                    break
                except Exception as e:
                    if attempt < max_attempts - 1:
                        self.logger.warning(f"Attempt {attempt + 1} failed to fill destination, retrying...")
                        time.sleep(2)
                    else:
                        raise e
            
            # Select date
            self._select_date()
            
            # Search for trips
            self._search_trips()
            
            # Extract results
            trips = self._extract_results()
            
            # Save screenshot if verbose
            if self.verbose:
                self._save_screenshot()
            
            # Log results
            if trips:
                self.logger.info(f"Found {len(trips)} trips matching criteria")
                if self.verbose:
                    for i, trip in enumerate(trips, 1):
                        self.logger.info(f"{i}. {trip.get('tipo', 'N/A')} - {trip.get('salida', 'N/A')} to {trip.get('llegada', 'N/A')} - {trip.get('precio', 'N/A')}")
            else:
                self.logger.info("No trips found matching criteria")
            
            return trips
            
        except Exception as e:
            self.logger.error(f"Scraping failed: {e}")
            self._save_screenshot("renfe_error.png")
            raise
        finally:
            self.driver.quit()


def display_results(trips: List[Dict[str, str]], date_str: str):
    """Display the extracted trip information in a formatted manner"""
    if trips:
        print(f"\n✅ Trips found for {date_str}:")
        print("=" * 70)
        for i, trip in enumerate(trips, 1):
            estado = "❌ TREN COMPLETO" if trip.get("completo") else "✅ Disponible"
            print(f"{i}. {trip.get('tipo', 'N/A')} - {estado}")
            print(f"   🕐 Departure: {trip.get('salida', 'N/A')} | Arrival: {trip.get('llegada', 'N/A')}")
            print(f"   ⏱️ Duration: {trip.get('duracion', 'N/A')}")
            print(f"   💰 Price: {trip.get('precio', 'N/A')}")
            print("-" * 70)
        print(f"\nTotal: {len(trips)} trips")
    else:
        print(f"\n❌ No trips found for {date_str}")


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Search for Renfe train tickets with advanced filtering")
    
    # Required arguments
    parser.add_argument("origin", help="Origin station (e.g., 'Girona')")
    parser.add_argument("destination", help="Destination station (e.g., 'Barcelona-Sants')")
    
    # Optional arguments
    parser.add_argument("-d", "--days", type=int, default=1, help="Days from today (0-15, default: 1)")
    parser.add_argument("-t", "--train-types", choices=["AVE", "AVANT", "MD", "ALL"], nargs="+", 
                      default=["AVANT"], help="Train types to include (default: AVANT)")
    
    # Time filters
    time_filter_group = parser.add_argument_group("Time filters (optional)")
    time_filter_group.add_argument("--before", metavar="HH:MM", help="Only show trains departing before specified time (e.g., '08:30')")
    time_filter_group.add_argument("--after", metavar="HH:MM", help="Only show trains departing after specified time (e.g., '16:00')")
    
    # Other options
    parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode (less verbose output)")
    
    args = parser.parse_args()
    
    # Validate days
    if not 0 <= args.days <= 15:
        parser.error("Days must be between 0 and 15")
    
    # Create time filter if specified
    time_filter = None
    if args.before and args.after:
        parser.error("Cannot use both --before and --after at the same time")
    elif args.before:
        time_filter = ('before', args.before)
    elif args.after:
        time_filter = ('after', args.after)
    
    return args, time_filter


def main():
    """Main execution with command-line arguments"""
    args, time_filter = parse_args()
    
    try:
        # Create scraper with command-line arguments
        scraper = RenfeSeleniumScraper(
            origin=args.origin,
            destination=args.destination,
            days_from_now=args.days,
            train_types=args.train_types,
            time_filter=time_filter,
            verbose=not args.quiet
        )
        
        # Run scraper
        results = scraper.run()
        
        # Always display results, even in quiet mode
        display_results(results, scraper.date_str)
        
    except Exception as e:
        logging.error(f"Failed to run scraper: {e}")
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())