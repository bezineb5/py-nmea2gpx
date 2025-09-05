import datetime
import logging
import shutil
from typing import List, Optional, Dict, Union, TextIO, Type, Generator, Iterable
from pathlib import Path
from dataclasses import dataclass
import traceback

log = logging.getLogger(__name__)

def validate_latitude(lat: float) -> bool:
    """Validate latitude value.
    
    Args:
        lat: Latitude in decimal degrees
        
    Returns:
        True if latitude is valid (-90 to 90), False otherwise
    """
    return -90.0 <= lat <= 90.0

def validate_longitude(lon: float) -> bool:
    """Validate longitude value.
    
    Args:
        lon: Longitude in decimal degrees
        
    Returns:
        True if longitude is valid (-180 to 180), False otherwise
    """
    return -180.0 <= lon <= 180.0

def validate_coordinates(lat: float, lon: float) -> bool:
    """Validate both latitude and longitude coordinates.
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        
    Returns:
        True if both coordinates are valid, False otherwise
    """
    return validate_latitude(lat) and validate_longitude(lon)

def detect_gps_errors(lat: float, lon: float) -> List[str]:
    """Detect common GPS coordinate errors and return a list of issues.
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        
    Returns:
        List of detected error messages (empty if no errors)
    """
    errors = []
    
    # Check for zero coordinates (common GPS startup issue)
    if lat == 0.0 and lon == 0.0:
        errors.append("Zero coordinates detected (likely GPS startup)")
        errors.append("Coordinates at null island (0,0) - likely invalid")
    
    # Check for coordinates that are too close to zero (suspicious)
    elif abs(lat) < 0.0001 and abs(lon) < 0.0001:
        errors.append("Coordinates very close to zero (suspicious)")
    
    # Note: Coordinates at equator (lat=0.0) and prime meridian (lon=0.0) are normal
    # and should not be flagged as errors
    
    # Check for coordinates that are exactly on the poles
    if abs(lat) == 90.0:
        errors.append("Latitude at pole - verify if correct")
    
    # Check for coordinates that are exactly on the 180th meridian
    if abs(lon) == 180.0:
        errors.append("Longitude at 180th meridian - verify if correct")
    
    return errors

def should_reject_coordinates(lat: float, lon: float, strict: bool = False) -> bool:
    """Determine if coordinates should be rejected based on validation rules.
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        strict: If True, reject suspicious coordinates
        
    Returns:
        True if coordinates should be rejected, False otherwise
    """
    if not strict:
        return False
    
    # In strict mode, reject coordinates that are likely invalid
    errors = detect_gps_errors(lat, lon)
    
    # Reject coordinates with certain types of errors in strict mode
    rejectable_errors = [
        "Zero coordinates detected (likely GPS startup)",
        "Coordinates very close to zero (suspicious)",
        "Coordinates at null island (0,0) - likely invalid"
    ]
    
    return any(error in errors for error in rejectable_errors)

class ChecksumError(ValueError):
    """Exception raised when NMEA sentence checksum validation fails."""
    pass

class NMEASentence:
    """Base class for NMEA sentences"""
    
    SENTENCE_TYPES: Dict[str, Type["NMEASentence"]] = {}  # Initialized after all classes defined
    
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "") -> None:
        self.talker: str = talker
        self.sentence: List[str] = sentence
        self.checksum: str = checksum
        self.sentence_type: str = sentence_type
        self.is_valid: bool = self._validate_checksum()
    
    def _validate_checksum(self) -> bool:
        """Validate the checksum of a NMEA sentence"""
        # The checksum was already validated during parsing
        return True
    
    @staticmethod
    def parse(line: str, strict_validation: bool = False) -> 'NMEASentence':
        """Parse a NMEA sentence and return the appropriate sentence object"""
        if not line.startswith('$'):
            raise ValueError("Invalid NMEA sentence")
            
        try:
            # Remove null bytes from the line first
            line = line.replace('\x00', '')
            
            # Remove leading $ and trailing whitespace/newline
            line = line.strip()
            
            # Split into main sentence and checksum
            if '*' in line:
                sentence, checksum = line.split('*')
            else:
                raise ValueError("Missing checksum")
            
            # Calculate checksum from characters between $ and * (exclusive)
            calc_cksum = 0
            for c in sentence[1:]:  # Skip the leading $
                calc_cksum ^= ord(c)
                
            if f"{calc_cksum:02X}" != checksum.strip().upper():  # Make comparison case-insensitive
                # Add debug logging to show the raw sentence
                logging.debug(f"Raw NMEA sentence with failed checksum: {line}")
                logging.debug(f"Sentence part (before *): {sentence}")
                logging.debug(f"Checksum part (after *): {checksum}")
                logging.debug(f"Calculated checksum: {calc_cksum:02X}")
                raise ChecksumError(f"Checksum validation failed: expected {checksum}, got {calc_cksum:02X}")
            
            # Get talker ID and sentence type
            sentence_parts = sentence[1:].split(',')  # Remove leading $ before splitting
            sentence_id = sentence_parts[0]
            
            if len(sentence_id) < 5:
                raise ValueError("Invalid sentence ID")
                
            talker = sentence_id[0:2]
            sentence_type = sentence_id[2:]
            
            # Get the sentence data (excluding the sentence ID)
            sentence_data = sentence_parts[1:]
            
            # Create sentence object
            if sentence_type in NMEASentence.SENTENCE_TYPES:
                sentence_class = NMEASentence.SENTENCE_TYPES[sentence_type]
                if sentence_type in ['RMC', 'GGA']:
                    nmea = sentence_class(talker, sentence_data, checksum.strip(), sentence_type, strict_validation)
                else:
                    nmea = sentence_class(talker, sentence_data, checksum.strip(), sentence_type)
            else:
                # Unknown sentence type
                nmea = NMEASentence(talker, sentence_data, checksum.strip(), sentence_type)
            
            return nmea
                
        except ChecksumError:
            raise  # Re-raise checksum errors as is
        except Exception as e:
            raise ValueError(f"Error parsing NMEA sentence: {str(e)}")
                

@dataclass
class GSVSatellite:
    """Helper class to store satellite data from GSV sentence"""
    prn: Optional[int]
    elevation: Optional[int]
    azimuth: Optional[int]
    snr: Optional[int]

class GSA(NMEASentence):
    """
    GSA - GPS DOP and active satellites
    
        $GPGSA,A,3,04,05,09,12,,,,,,,,,2.5,1.3,2.1*39
        
        Where:
            A            Auto selection of 2D or 3D fix (M = manual)
            3            3D fix - values include:
                        1 = no fix
                        2 = 2D fix
                        3 = 3D fix
            04,05...     PRNs of satellites used for fix (space for 12)
            2.5          PDOP (dilution of precision)
            1.3          Horizontal dilution of precision (HDOP)
            2.1          Vertical dilution of precision (VDOP)
            *39          the checksum data, always begins with *
    """
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "GSA") -> None:
        super().__init__(talker, sentence, checksum, sentence_type)
        self.mode_auto: str = sentence[0]  # Auto/Manual
        self.mode_fix_type: Optional[int] = int(sentence[1]) if sentence[1] else None  # 1,2,3
        
        # Parse satellite IDs (up to 12)
        self.sv_ids: List[int] = []
        for i in range(2, 14):
            if i < len(sentence) and sentence[i]:
                self.sv_ids.append(int(sentence[i]))
        
        # Parse DOP values
        self.pdop: Optional[float] = float(sentence[14]) if len(sentence) > 14 and sentence[14] else None
        self.hdop: Optional[float] = float(sentence[15]) if len(sentence) > 15 and sentence[15] else None
        self.vdop: Optional[float] = float(sentence[16]) if len(sentence) > 16 and sentence[16] else None


class VTG(NMEASentence):
    """
    VTG - Track made good and Ground speed
    
        $GPVTG,054.7,T,034.4,M,005.5,N,010.2,K*48
        
        Where:
            054.7,T      True track made good (degrees)
            034.4,M      Magnetic track made good
            005.5,N      Ground speed, knots
            010.2,K      Ground speed, Kilometers per hour
            *48          Checksum
    """
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "VTG") -> None:
        super().__init__(talker, sentence, checksum, sentence_type)
        self.true_track: Optional[float] = float(sentence[0]) if sentence[0] else None
        self.mag_track: Optional[float] = float(sentence[2]) if sentence[2] else None
        self.speed_knots: Optional[float] = float(sentence[4]) if sentence[4] else None
        self.speed_kmh: Optional[float] = float(sentence[6]) if sentence[6] else None


class GSV(NMEASentence):
    """
    GSV - Satellites in view
    
        $GPGSV,3,1,11,03,03,111,00,04,15,270,00,06,01,010,00,13,06,292,00*74
        
        Where:
            3           Number of sentences for full data
            1           sentence 1 of 3
            11          Number of satellites in view
            03          Satellite PRN number
            03          Elevation in degrees
            111         Azimuth, degrees from true north
            00          SNR - higher is better
                       for up to 4 satellites per sentence
            *74          the checksum data, always begins with *
    """
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "GSV") -> None:
        super().__init__(talker, sentence, checksum, sentence_type)
        self.num_messages: int = int(sentence[0])
        self.msg_num: int = int(sentence[1])
        self.sats_in_view: int = int(sentence[2])
        
        # Parse satellite data (up to 4 satellites per message)
        self.sat_data: List[GSVSatellite] = []
        for i in range(0, 4):
            base_idx = 3 + (i * 4)
            if base_idx + 3 < len(sentence) and sentence[base_idx]:
                sat = GSVSatellite(
                    int(sentence[base_idx]),  # PRN
                    int(sentence[base_idx + 1]) if sentence[base_idx + 1] else None,  # Elevation
                    int(sentence[base_idx + 2]) if sentence[base_idx + 2] else None,  # Azimuth
                    int(sentence[base_idx + 3]) if sentence[base_idx + 3] else None   # SNR
                )
                self.sat_data.append(sat)

class RMC(NMEASentence):
    """
    RMC - Recommended Minimum Navigation Information
    
        $GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
        
        Where:
            123519       Fix taken at 12:35:19 UTC
            A            Navigation receiver warning A = OK, V = warning
            4807.038,N   Latitude 48 deg 07.038' N
            01131.000,E  Longitude 11 deg 31.000' E
            022.4        Speed over ground in knots
            084.4        Track angle in degrees True
            230394       Date - 23rd of March 1994
            003.1,W      Magnetic Variation
            *6A          Checksum
    """
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "RMC", strict_validation: bool = False) -> None:
        super().__init__(talker, sentence, checksum, sentence_type)
        
        # Parse time and date first
        self.time: Optional[datetime.time] = None
        self.date: Optional[datetime.date] = None
        
        if sentence[0]:  # Time
            try:
                hour = int(sentence[0][0:2])
                minute = int(sentence[0][2:4])
                second = int(sentence[0][4:6])
                self.time = datetime.time(hour, minute, second)
            except (ValueError, IndexError):
                pass
                
        if len(sentence) > 8 and sentence[8]:  # Date
            try:
                day = int(sentence[8][0:2])
                month = int(sentence[8][2:4])
                year = 2000 + int(sentence[8][4:6])  # Assuming 20xx
                self.date = datetime.date(year, month, day)
            except (ValueError, IndexError):
                pass
        
        self.status: bool = sentence[1] == 'A' if len(sentence) > 1 else False
        
        # Parse latitude
        if len(sentence) > 3 and sentence[2] and sentence[3]:
            lat = float(sentence[2])
            lat_deg = int(lat / 100)
            lat_min = lat - (lat_deg * 100)
            self.latitude: Optional[float] = lat_deg + (lat_min / 60)
            if sentence[3] == 'S':
                self.latitude = -self.latitude
                
            # Validate latitude
            if not validate_latitude(self.latitude):
                logging.warning(f"Invalid latitude in RMC: {self.latitude}")
                self.latitude = None
        else:
            self.latitude = None
            
        # Parse longitude
        if len(sentence) > 5 and sentence[4] and sentence[5]:
            lon = float(sentence[4])
            lon_deg = int(lon / 100)
            lon_min = lon - (lon_deg * 100)
            self.longitude: Optional[float] = lon_deg + (lon_min / 60)
            if sentence[5] == 'W':
                self.longitude = -self.longitude
                
            # Validate longitude
            if not validate_longitude(self.longitude):
                logging.warning(f"Invalid longitude in RMC: {self.longitude}")
                self.longitude = None
            else:
                # Check for GPS errors if we have both coordinates
                if self.latitude is not None:
                    errors = detect_gps_errors(self.latitude, self.longitude)
                    for error in errors:
                        logging.warning(f"RMC coordinate issue: {error} (lat={self.latitude}, lon={self.longitude})")
                    
                    # Reject coordinates in strict mode
                    if should_reject_coordinates(self.latitude, self.longitude, strict_validation):
                        logging.warning(f"Rejecting RMC coordinates in strict mode: lat={self.latitude}, lon={self.longitude}")
                        self.latitude = None
                        self.longitude = None
        else:
            self.longitude = None
            
        # Parse speed and course
        self.speed: Optional[float] = float(sentence[6]) if len(sentence) > 6 and sentence[6] else None
        self.course: Optional[float] = float(sentence[7]) if len(sentence) > 7 and sentence[7] else None
        
        # Parse magnetic variation
        if len(sentence) > 9 and sentence[9]:
            self.mag_var: Optional[float] = float(sentence[9])
            if len(sentence) > 10 and sentence[10] == 'W':
                self.mag_var = -self.mag_var
        else:
            self.mag_var = None

class GGA(NMEASentence):
    """
    GGA - Global Positioning System Fix Data
    
        $GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
        
        Where:
            123519       Fix taken at 12:35:19 UTC
            4807.038,N   Latitude 48 deg 07.038' N
            01131.000,E  Longitude 11 deg 31.000' E
            1            Fix quality: 0 = invalid
                                    1 = GPS fix (SPS)
                                    2 = DGPS fix
                                    3 = PPS fix
                                    4 = Real Time Kinematic
                                    5 = Float RTK
                                    6 = estimated (dead reckoning)
                                    7 = Manual input mode
                                    8 = Simulation mode
            08           Number of satellites being tracked
            0.9          Horizontal dilution of position
            545.4,M      Altitude, Meters, above mean sea level
            46.9,M       Height of geoid (mean sea level) above WGS84 ellipsoid
            (empty field) time in seconds since last DGPS update
            (empty field) DGPS station ID number
            *47          Checksum
    """
    def __init__(self, talker: str, sentence: List[str], checksum: str, sentence_type: str = "GGA", strict_validation: bool = False) -> None:
        super().__init__(talker, sentence, checksum, sentence_type)
        
        # Parse time
        self.time: Optional[datetime.time] = None
        if sentence[0]:
            try:
                hour = int(sentence[0][0:2])
                minute = int(sentence[0][2:4])
                second = int(sentence[0][4:6])
                self.time = datetime.time(hour, minute, second)
            except (ValueError, IndexError):
                pass
        
        # Parse latitude
        if sentence[1] and sentence[2]:
            lat = float(sentence[1])
            lat_deg = int(lat / 100)
            lat_min = lat - (lat_deg * 100)
            self.latitude: Optional[float] = lat_deg + (lat_min / 60)
            if sentence[2] == 'S':
                self.latitude = -self.latitude
                
            # Validate latitude
            if not validate_latitude(self.latitude):
                logging.warning(f"Invalid latitude in GGA: {self.latitude}")
                self.latitude = None
        else:
            self.latitude = None
            
        # Parse longitude
        if sentence[3] and sentence[4]:
            lon = float(sentence[3])
            lon_deg = int(lon / 100)
            lon_min = lon - (lon_deg * 100)
            self.longitude: Optional[float] = lon_deg + (lon_min / 60)
            if sentence[4] == 'W':
                self.longitude = -self.longitude
                
            # Validate longitude
            if not validate_longitude(self.longitude):
                logging.warning(f"Invalid longitude in GGA: {self.longitude}")
                self.longitude = None
            else:
                # Check for GPS errors if we have both coordinates
                if self.latitude is not None:
                    errors = detect_gps_errors(self.latitude, self.longitude)
                    for error in errors:
                        logging.warning(f"GGA coordinate issue: {error} (lat={self.latitude}, lon={self.longitude})")
                    
                    # Reject coordinates in strict mode
                    if should_reject_coordinates(self.latitude, self.longitude, strict_validation):
                        logging.warning(f"Rejecting GGA coordinates in strict mode: lat={self.latitude}, lon={self.longitude}")
                        self.latitude = None
                        self.longitude = None
        else:
            self.longitude = None
        
        # Parse fix quality and other numeric fields
        self.fix_quality: Optional[int] = int(sentence[5]) if sentence[5] else None
        self.num_sats: Optional[int] = int(sentence[6]) if sentence[6] else None
        self.hdop: Optional[float] = float(sentence[7]) if sentence[7] else None
        self.altitude: Optional[float] = float(sentence[8]) if sentence[8] else None
        self.geoid_height: Optional[float] = float(sentence[10]) if len(sentence) > 10 and sentence[10] else None
        self.dgps_update: Optional[float] = float(sentence[12]) if len(sentence) > 12 and sentence[12] else None
        self.dgps_station: Optional[int] = int(sentence[13]) if len(sentence) > 13 and sentence[13] else None

# Initialize sentence types after all classes are defined
NMEASentence.SENTENCE_TYPES = {
    'RMC': RMC,
    'GGA': GGA,
    'GSA': GSA,
    'GSV': GSV,
    'VTG': VTG
} 

class GPXWriter:
    """Writes GPX format files with NMEA extensions."""
    
    def __init__(self, output_file: Path, compact: bool = False) -> None:
        self.output_file: Path = Path(output_file)
        self.track_started: bool = False
        self.f: Optional[TextIO] = None
        self.compact: bool = compact

    def __enter__(self) -> 'GPXWriter':
        self.f = self.output_file.open('w')
        self.write_line('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
        gpx_header = '''<gpx xmlns="http://www.topografix.com/GPX/1/1" '''
        gpx_header += 'xmlns:nmea="http://www.nmea.org" '
        gpx_header += 'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v2" '
        gpx_header += 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        gpx_header += 'creator="nmea2gpx" version="1.1" '
        gpx_header += 'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 '
        gpx_header += 'http://www.topografix.com/GPX/1/1/gpx.xsd '
        gpx_header += 'http://www.garmin.com/xmlschemas/TrackPointExtension/v2 '
        gpx_header += 'http://www.garmin.com/xmlschemas/TrackPointExtensionv2.xsd">'
        self.write_line(gpx_header)
        return self

    def __exit__(self, exc_type: Optional[Type[BaseException]], 
                 exc_val: Optional[BaseException], 
                 exc_tb: Optional[object]) -> None:
        if self.track_started:
            self.end_track()
        if self.f:
            self.write_line('</gpx>')
            self.f.close()

    def write_line(self, data: str) -> None:
        if self.compact:
            self.f.write(data.strip())
        else:
            self.f.write(data + '\n')

    def start_track(self, name: Optional[str] = None) -> None:
        if not self.f:
            raise RuntimeError("File not opened")
        self.write_line('  <trk>')
        if name:
            self.write_line(f'    <name>{name}</name>')
        self.write_line('    <trkseg>')
        self.track_started = True

    def add_trackpoint(self, rmc: Optional[RMC] = None, 
                      gga: Optional[GGA] = None,
                      gsa: Optional[GSA] = None, 
                      vtg: Optional[VTG] = None,
                      gsv: Optional[GSV] = None) -> None:
        """Add a trackpoint from NMEA sentence data."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        if not (rmc or gga):
            return

        # Use RMC for position if available, otherwise GGA
        pos = rmc if rmc else gga
        assert pos is not None  # for type checker
        
        # Check that we have valid coordinates
        if pos.latitude is None or pos.longitude is None:
            return
        
        self.write_line(f'      <trkpt lat="{pos.latitude:.8f}" lon="{pos.longitude:.8f}">')
        
        if gga and gga.altitude is not None:
            self.write_line(f'        <ele>{gga.altitude:.3f}</ele>')
            
        if pos.time:
            # Format timestamp in ISO 8601 format with UTC timezone
            ts = pos.time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            self.write_line(f'        <time>{ts}</time>')

        if gga and gga.num_sats:
            self.write_line(f'        <sat>{gga.num_sats}</sat>')

        # Add NMEA extensions
        self._write_extensions(rmc, gga, gsa, vtg, gsv)

    def _write_extensions(self, rmc: Optional[RMC], 
                         gga: Optional[GGA],
                         gsa: Optional[GSA], 
                         vtg: Optional[VTG],
                         gsv: Optional[GSV]) -> None:
        """Write NMEA extensions to the GPX file."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        self.write_line('        <extensions>')
        
        # First add Garmin TrackPointExtension v2 for supported data
        has_tpx_data = False
        
        # Check if we have any data that fits in the TrackPointExtension schema
        if (rmc and rmc.speed) or \
           (vtg and vtg.true_track) or \
           (gsa and gsa.hdop) or \
           (gga and gga.hdop):
            has_tpx_data = True
            
        if has_tpx_data:
            self.write_line('          <gpxtpx:TrackPointExtension>')
            # Add heart rate (not available in our data but included for completeness)
            # self.write_line('            <gpxtpx:hr>100</gpxtpx:hr>')
            
            # Add cadence if available (not in our current data)
            # self.write_line('            <gpxtpx:cad>90</gpxtpx:cad>')
            
            # Add speed from RMC if available (in m/s)
            if rmc and rmc.speed:
                # Convert knots to meters per second (1 knot = 0.514444 m/s)
                speed_ms = rmc.speed * 0.514444
                self.write_line(f'            <gpxtpx:speed>{speed_ms:.3f}</gpxtpx:speed>')
            elif vtg and vtg.speed_kmh:
                # Convert km/h to m/s
                speed_ms = vtg.speed_kmh / 3.6
                self.write_line(f'            <gpxtpx:speed>{speed_ms:.3f}</gpxtpx:speed>')
            
            # Add course
            if rmc and rmc.course:
                self.write_line(f'            <gpxtpx:course>{rmc.course:.2f}</gpxtpx:course>')
            elif vtg and vtg.true_track:
                self.write_line(f'            <gpxtpx:course>{vtg.true_track:.2f}</gpxtpx:course>')
                
            # Add HDOP
            if gsa and gsa.hdop:
                self.write_line(f'            <gpxtpx:hdop>{gsa.hdop:.2f}</gpxtpx:hdop>')
            elif gga and gga.hdop:
                self.write_line(f'            <gpxtpx:hdop>{gga.hdop:.2f}</gpxtpx:hdop>')
                
            self.write_line('          </gpxtpx:TrackPointExtension>')
        
        # Now add remaining NMEA-specific data that doesn't fit the Garmin schema
        if rmc:
            self._write_rmc_extensions(rmc)
        if gga:
            self._write_gga_extensions(gga)
        if gsa:
            self._write_gsa_extensions(gsa)
        if vtg:
            self._write_vtg_extensions(vtg)
        if gsv:
            self._write_gsv_extensions(gsv)
            
        self.write_line('        </extensions>')
        self.write_line('      </trkpt>')

    def _write_rmc_extensions(self, rmc: RMC) -> None:
        """Write RMC-specific extensions."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        # Skip speed and course as they're handled by Garmin TrackPointExtension
        # Only write mag_var which isn't covered by Garmin schema
        if rmc.mag_var:
            self.write_line(f'          <nmea:magvar>{rmc.mag_var:.2f}</nmea:magvar>')

    def _write_gga_extensions(self, gga: GGA) -> None:
        """Write GGA-specific extensions."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        if gga.fix_quality:
            self.write_line(f'          <nmea:fix_quality>{gga.fix_quality}</nmea:fix_quality>')
        # Skip HDOP as it's handled by Garmin TrackPointExtension
        if gga.altitude and gga.geoid_height:
            self.write_line(f'          <nmea:geoid_height>{gga.geoid_height:.3f}</nmea:geoid_height>')
        if gga.dgps_update:
            self.write_line(f'          <nmea:dgps_age>{gga.dgps_update:.1f}</nmea:dgps_age>')
        if gga.dgps_station:
            self.write_line(f'          <nmea:dgps_station>{gga.dgps_station}</nmea:dgps_station>')

    def _write_gsa_extensions(self, gsa: GSA) -> None:
        """Write GSA-specific extensions."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        if gsa.mode_fix_type:
            self.write_line(f'          <nmea:fix_type>{gsa.mode_fix_type}</nmea:fix_type>')
        if gsa.pdop:
            self.write_line(f'          <nmea:pdop>{gsa.pdop:.2f}</nmea:pdop>')
        # Skip HDOP as it's handled by Garmin TrackPointExtension
        if gsa.vdop:
            self.write_line(f'          <nmea:vdop>{gsa.vdop:.2f}</nmea:vdop>')
        if gsa.sv_ids:
            sv_ids_str = ','.join(map(str, gsa.sv_ids))
            self.write_line(f'          <nmea:active_sats>{sv_ids_str}</nmea:active_sats>')

    def _write_vtg_extensions(self, vtg: VTG) -> None:
        """Write VTG-specific extensions."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        # Skip true_track and speed as they're handled by Garmin TrackPointExtension
        # Only write mag_track and speed formats not covered by Garmin schema
        if vtg.mag_track:
            self.write_line(f'          <nmea:mag_track>{vtg.mag_track:.2f}</nmea:mag_track>')
        if vtg.speed_knots:
            self.write_line(f'          <nmea:speed_knots>{vtg.speed_knots:.3f}</nmea:speed_knots>')

    def _write_gsv_extensions(self, gsv: GSV) -> None:
        """Write GSV-specific extensions."""
        if not self.f:
            raise RuntimeError("File not opened")
            
        if gsv.sat_data:
            self.write_line('          <nmea:satellites>')
            for i, sat in enumerate(gsv.sat_data[:4]):  # Limit to first 4 sats
                self.write_line('            <nmea:sat>')
                self.write_line(f'              <nmea:prn>{sat.prn}</nmea:prn>')
                if sat.elevation is not None:
                    self.write_line(f'              <nmea:elevation>{sat.elevation}</nmea:elevation>')
                if sat.azimuth is not None:
                    self.write_line(f'              <nmea:azimuth>{sat.azimuth}</nmea:azimuth>')
                if sat.snr is not None:
                    self.write_line(f'              <nmea:snr>{sat.snr}</nmea:snr>')
                self.write_line('            </nmea:sat>')
            self.write_line('          </nmea:satellites>')

    def end_track(self) -> None:
        """End the current track segment."""
        if not self.f:
            raise RuntimeError("File not opened")
        self.write_line('    </trkseg>')
        self.write_line('  </trk>')
        self.track_started = False 

def parse_nmea_stream(input_file: Path, strict_validation: bool = False) -> Generator[NMEASentence, None, None]:
    """Parse NMEA sentences from a file, yielding valid sentences.
    
    Args:
        input_file: Path to input NMEA file
        
    Yields:
        Valid NMEASentence objects
        
    Raises:
        OSError: If file operations fail
    """
    try:
        with input_file.open('rb') as f:  # Open in binary mode
            for line in f:
                try:
                    # Skip non-NMEA lines (must start with $)
                    if not line.startswith(b'$'):
                        continue
                        
                    # Decode line as ASCII, ignoring errors
                    # NMEA is ASCII-based, so this is safe
                    line_str = line.decode('ascii', errors='ignore').strip()
                    
                    # Remove null bytes that may be present in preallocated files
                    line_str = line_str.replace('\x00', '')
                    
                    # Skip empty lines after null removal
                    if not line_str.strip():
                        continue
                    
                    # Parse NMEA sentence
                    sentence = NMEASentence.parse(line_str, strict_validation)
                    
                    # Skip if checksum validation fails
                    if not sentence.is_valid:
                        continue
                        
                    yield sentence
                        
                except (ValueError, ChecksumError) as e:
                    logging.warning(f"Error parsing line in {input_file}: {e}")
                    continue
                except UnicodeDecodeError as e:
                    # Skip binary/non-ASCII data
                    continue
    except Exception as e:
        logging.error(f"Error reading file {input_file}: {e}")
        raise

# Type alias for point data
PointData = Dict[str, Optional[Union[RMC, GGA, GSA, VTG, GSV]]]

def group_nmea_points(sentences: Iterable[NMEASentence], 
                     time_window: float = 1.0) -> Generator[PointData, None, None]:
    """Group NMEA sentences into points based on timestamps.
    
    Args:
        sentences: Iterator of NMEA sentences
        time_window: Time window in seconds for grouping sentences
        
    Yields:
        Dictionary containing grouped NMEA sentences for each point
    """
    current_data: Dict[str, Optional[Union[NMEASentence, datetime.time, datetime.date]]] = {
        'rmc': None,
        'gga': None,
        'gsa': None,
        'vtg': None,
        'gsv': None,
        'last_time': None,
        'current_date': None  # Store current date from RMC
    }
    
    def get_point() -> PointData:
        """Extract point data from current_data."""
        # If we have both RMC and GGA, copy the date from RMC to GGA
        if current_data['rmc'] and current_data['gga']:
            rmc = current_data['rmc']
            gga = current_data['gga']
            assert isinstance(rmc, RMC)  # Type hints for mypy
            assert isinstance(gga, GGA)
            if rmc.time and rmc.date:
                # Create a datetime object from RMC's date and time
                rmc.time = datetime.datetime.combine(rmc.date, rmc.time)
                if gga.time:
                    # Create a datetime object from RMC's date and GGA's time
                    gga.time = datetime.datetime.combine(rmc.date, gga.time)
        # If we only have GGA but have a stored date, use that
        elif current_data['gga'] and current_data['current_date']:
            gga = current_data['gga']
            current_date = current_data['current_date']
            assert isinstance(gga, GGA)  # Type hints for mypy
            assert isinstance(current_date, datetime.date)
            if gga.time:
                # Create a datetime object from stored date and GGA's time
                gga.time = datetime.datetime.combine(current_date, gga.time)
                    
        return {
            'rmc': current_data['rmc'] if isinstance(current_data['rmc'], RMC) else None,
            'gga': current_data['gga'] if isinstance(current_data['gga'], GGA) else None,
            'gsa': current_data['gsa'] if isinstance(current_data['gsa'], GSA) else None,
            'vtg': current_data['vtg'] if isinstance(current_data['vtg'], VTG) else None,
            'gsv': current_data['gsv'] if isinstance(current_data['gsv'], GSV) else None
        }
    
    for sentence in sentences:
        # Get timestamp from RMC or GGA
        msg_time = None
        if isinstance(sentence, (RMC, GGA)):
            msg_time = sentence.time
            
            # If we have a timestamp and it's outside our window, yield the point
            if msg_time and current_data['last_time']:
                last_time = current_data['last_time']
                assert isinstance(last_time, datetime.time)  # Type hint for mypy
                
                # Convert times to seconds since midnight for comparison
                msg_secs = msg_time.hour * 3600 + msg_time.minute * 60 + msg_time.second + msg_time.microsecond/1000000
                last_secs = last_time.hour * 3600 + last_time.minute * 60 + last_time.second + last_time.microsecond/1000000
                
                time_diff = abs(msg_secs - last_secs)
                if time_diff > time_window:
                    if current_data['rmc'] or current_data['gga']:
                        yield get_point()
                    # Clear current data except GSA/GSV which may be used for multiple points
                    current_data['rmc'] = None
                    current_data['gga'] = None
                    current_data['vtg'] = None
                    current_data['last_time'] = None
        
        # Store the sentence based on its type
        if isinstance(sentence, RMC):
            # If we already have RMC data, yield the current point
            if current_data['rmc'] and current_data['gga']:
                yield get_point()
                current_data['rmc'] = None
                current_data['gga'] = None
                current_data['vtg'] = None
                current_data['last_time'] = None
            
            current_data['rmc'] = sentence
            current_data['last_time'] = msg_time
            if msg_time and sentence.date:
                current_data['current_date'] = sentence.date
        elif isinstance(sentence, GGA):
            # If we already have GGA data, yield the current point
            if current_data['gga'] and current_data['rmc']:
                yield get_point()
                current_data['rmc'] = None
                current_data['gga'] = None
                current_data['vtg'] = None
                current_data['last_time'] = None
                
            current_data['gga'] = sentence
            current_data['last_time'] = msg_time
        elif isinstance(sentence, GSA):
            current_data['gsa'] = sentence
        elif isinstance(sentence, VTG):
            current_data['vtg'] = sentence
        elif isinstance(sentence, GSV):
            current_data['gsv'] = sentence
    
    # Yield any remaining point data
    if current_data['rmc'] or current_data['gga']:
        yield get_point()

def create_backup(output_file: Path, backup_path: Path) -> None:
    """Create a backup copy of the output file.
    
    Args:
        output_file: Path to source file
        backup_path: Path to create backup at
        
    Raises:
        OSError: If backup creation fails
    """
    try:
        # Create backup directory if it doesn't exist
        backup_dir = backup_path.parent
        if backup_dir != Path('.'):
            backup_dir.mkdir(parents=True, exist_ok=True)
            
        # Copy the file to backup location
        shutil.copy2(output_file, backup_path)
        logging.info(f"Created backup of GPX file at: {backup_path}")
    except Exception as e:
        logging.error(f"Failed to create backup at {backup_path}: {e}")
        raise

def delete_source_files(files: List[Path]) -> None:
    """Delete the source files.
    
    Args:
        files: List of files to delete
        
    Note:
        Failures to delete individual files are logged but don't raise exceptions
    """
    for file in files:
        try:
            file.unlink()
            logging.info(f"Deleted source file: {file}")
        except Exception as e:
            logging.error(f"Failed to delete source file {file}: {e}")

def expand_input_patterns(input_patterns: List[str]) -> List[Path]:
    """Expand glob patterns and return sorted list of matching files.
    
    Args:
        input_patterns: List of input patterns (e.g. ["*.ubx", "*.nmea"])
        
    Returns:
        List of matching files sorted by name
        
    Raises:
        ValueError: If no files match any pattern
    """

        # Expand glob patterns and sort files
    input_files = []
    for pattern in input_patterns:
        # Convert pattern to Path object
        pattern_path = Path(pattern)
        # If pattern is absolute, use it as is, otherwise resolve relative to cwd
        if not pattern_path.is_absolute():
            pattern_path = Path.cwd() / pattern_path
            
        # Get parent directory and pattern
        parent = pattern_path.parent
        pattern_str = pattern_path.name
        
        # Find matching files
        matched_files = parent.glob(pattern_str)
        if not matched_files:
            raise ValueError(f"No files match pattern: {pattern}")
        input_files.extend(matched_files)

    return sorted(input_files)


def process_files(input_patterns: List[str], 
                output_file: Union[str, Path], 
                backup_path: Optional[Union[str, Path]] = None,
                delete_source: bool = False,
                raw_output: Optional[Union[str, Path]] = None,
                strict_validation: bool = False,
                compact: bool = False) -> None:
    """Process one or more NMEA files and write to a single GPX file.
    
    Args:
        input_patterns: List of input NMEA file patterns to process
        output_file: Path to write the GPX output
        backup_path: Optional path to create a backup copy of the GPX file
        delete_source: Optional flag to delete source files after successful conversion
        raw_output: Optional path to write concatenated raw input
    
    Raises:
        ValueError: If NMEA parsing fails
        ChecksumError: If NMEA checksum validation fails
        OSError: If file operations fail
    """
    
    # Convert all paths to Path objects
    input_files = expand_input_patterns(input_patterns)
    if not input_files:
        raise ValueError("No input files found")
    output_file = Path(output_file)
    if backup_path is not None:
        backup_path = Path(backup_path)
    if raw_output is not None:
        raw_output = Path(raw_output)
    
    # Sort input files once
    sorted_files = sorted(input_files)
    
    # Keep track of successfully processed files
    processed_files: List[Path] = []
    conversion_successful: bool = False
    
    try:
        # If raw output is requested, concatenate all input files with null byte removal
        if raw_output:
            with raw_output.open('wb') as outfile:
                for input_file in sorted_files:
                    try:
                        with input_file.open('rb') as infile:
                            # Read and write line by line, removing null bytes
                            for line in infile:
                                # Remove null bytes from the line
                                cleaned_line = line.replace(b'\x00', b'')
                                # Only write non-empty lines
                                if cleaned_line.strip():
                                    outfile.write(cleaned_line)
                    except Exception as e:
                        logging.error(f"Error concatenating file {input_file}: {e}")
                        continue
        
        with GPXWriter(output_file, compact=compact) as writer:
            writer.start_track()
            
            # Process files in sorted order
            for input_file in sorted_files:
                try:
                    logging.info(f"Processing file: {input_file}")
                    # Create a streaming pipeline for NMEA data
                    sentences = parse_nmea_stream(input_file, strict_validation)
                    for point in group_nmea_points(sentences):
                        logging.debug(f"Processing point: RMC={point['rmc']}, GGA={point['gga']}")
                        writer.add_trackpoint(
                            rmc=point['rmc'] if isinstance(point['rmc'], RMC) else None,
                            gga=point['gga'] if isinstance(point['gga'], GGA) else None,
                            gsa=point['gsa'] if isinstance(point['gsa'], GSA) else None,
                            vtg=point['vtg'] if isinstance(point['vtg'], VTG) else None,
                            gsv=point['gsv'] if isinstance(point['gsv'], GSV) else None
                        )
                    processed_files.append(input_file)
                    
                except Exception as e:
                    logging.error(f"Error processing file {input_file}:")
                    logging.error(traceback.format_exc())
                    # Continue with next file
                    continue
        
        conversion_successful = True
        
        # Create backup if backup path is provided
        if backup_path:
            try:
                create_backup(output_file, backup_path)
            except Exception as e:
                logging.error(f"Failed to create backup at {backup_path}: {e}")
                # Don't set conversion_successful to False as the main conversion worked
        
        # Delete source files if requested and conversion was successful
        if delete_source and conversion_successful and processed_files:
            delete_source_files(processed_files)
    
    except Exception as e:
        logging.error(f"Error during GPX conversion:")
        logging.error(traceback.format_exc())
        raise

def parse_arguments():
    """Parse command line arguments."""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description='Convert NMEA GPS data to GPX format'
    )
    
    parser.add_argument(
        'input_patterns',
        nargs='+',
        help='One or more input file patterns (e.g. "/Volume/sdcard/*.ubx")'
    )
    
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output GPX file'
    )
    
    parser.add_argument(
        '-b', '--backup',
        help='Create a backup copy of the output file at this location'
    )
    
    parser.add_argument(
        '-d', '--delete-source',
        action='store_true',
        help='Delete source files after successful conversion'
    )
    
    parser.add_argument(
        '-r', '--raw-output',
        help='Write concatenated raw input to this file'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        const=logging.DEBUG,
        default=logging.INFO,
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--strict-validation',
        action='store_true',
        help='Enable strict coordinate validation (reject suspicious coordinates)'
    )
    
    parser.add_argument(
        '--compact',
        action='store_true',
        help='Write compact GPX file'
    )
    
    return parser.parse_args()

def main():
    """Main entry point for the script."""
    args = parse_arguments()
    
    # Configure logging
    logging.basicConfig(
        level=args.verbose,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Convert paths to Path objects
        input_patterns = [Path(f) for f in args.input_patterns]
        output_file = Path(args.output)
        backup_path = Path(args.backup) if args.backup else None
        raw_output = Path(args.raw_output) if args.raw_output else None
        
        # Process the files
        process_files(
            input_patterns=input_patterns,
            output_file=output_file,
            backup_path=backup_path,
            delete_source=args.delete_source,
            raw_output=raw_output,
            strict_validation=args.strict_validation,
            compact=args.compact
        )
        
    except Exception as e:
        logging.error(str(e))
        return 1
        
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
