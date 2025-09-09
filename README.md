# nmea2gpx

A Python tool for converting NMEA GPS data to GPX format with comprehensive coordinate validation.

## Features

- **NMEA to GPX Conversion**: Converts NMEA sentences (RMC, GGA, GSA, VTG, GSV) to standard GPX format
- **Coordinate Validation**: Built-in validation to detect and handle invalid or suspicious GPS coordinates
- **Strict Mode**: Option to reject coordinates that are likely invalid (zero coordinates, null island, etc.)
- **Comprehensive Logging**: Detailed warnings and error messages for coordinate issues
- **Multiple Input Support**: Process multiple NMEA files with glob patterns
- **Backup Support**: Optional backup creation before processing
- **Raw Output**: Option to concatenate raw input files
- **Null Byte Handling**: Automatically removes null bytes (0x00) from preallocated/padded files

## Installation

### Option 1: Install from PyPI (Recommended)

```bash
pip install nmea2gpx
```

### Option 2: Install from Source

```bash
# Clone the repository
git clone https://github.com/bezineb5/py-nmea2gpx.git
cd py-nmea2gpx

# Install the package
pip install .
```

### Option 3: Build and Install Wheel

```bash
# Clone the repository
git clone https://github.com/bezineb5/py-nmea2gpx.git
cd py-nmea2gpx

# Install build tools
pip install build

# Build the wheel
python3 -m build

# Install the wheel
pip install dist/nmea2gpx-0.1-py3-none-any.whl
```

### Dependencies

The package has no external dependencies - it uses only Python standard library modules.

## Usage

### Basic Usage

After installation, you can use the `nmea2gpx` command:

```bash
# Convert a single NMEA file to GPX
nmea2gpx input.nmea -o output.gpx

# Convert multiple files using glob patterns
nmea2gpx "*.nmea" "*.ubx" -o output.gpx
```

Or run directly as a Python module:

```bash
# Convert a single NMEA file to GPX
python3 -m nmea2gpx input.nmea -o output.gpx

# Convert multiple files using glob patterns
python3 -m nmea2gpx "*.nmea" "*.ubx" -o output.gpx
```

If running from source without installation:

```bash
# Convert a single NMEA file to GPX
python3 nmea2gpx.py input.nmea -o output.gpx

# Convert multiple files using glob patterns
python3 nmea2gpx.py "*.nmea" "*.ubx" -o output.gpx
```

### Coordinate Validation

The tool includes comprehensive coordinate validation to detect common GPS issues:

#### Basic Validation
- **Latitude**: Must be between -90° and +90°
- **Longitude**: Must be between -180° and +180°

#### GPS Error Detection
The tool detects and warns about:
- Zero coordinates (0,0) - likely GPS startup issue
- Coordinates very close to zero (< 0.0001°)
- Coordinates at poles (90°, -90°)
- Coordinates at 180th meridian

#### Strict Validation Mode

Use `--strict-validation` to reject coordinates that are likely invalid:

```bash
# Reject suspicious coordinates
nmea2gpx input.nmea -o output.gpx --strict-validation
```

In strict mode, the following coordinates are rejected:
- Zero coordinates (0,0)
- Coordinates very close to zero
- Coordinates at null island

### Command Line Options

```bash
nmea2gpx [OPTIONS] INPUT_PATTERNS... -o OUTPUT_FILE

Options:
  -o, --output FILE          Output GPX file (required)
  -b, --backup PATH          Create backup copy of output file
  -d, --delete-source        Delete source files after successful conversion
  -r, --raw-output FILE      Write concatenated raw input to file
  --strict-validation        Enable strict coordinate validation
  -v, --verbose              Enable verbose logging
  -h, --help                 Show help message
```

### Examples

```bash
# Basic conversion with warnings
nmea2gpx gps_data.nmea -o track.gpx

# Strict validation with verbose logging
nmea2gpx gps_data.nmea -o track.gpx --strict-validation -v

# Process multiple files with backup
nmea2gpx "*.nmea" -o combined.gpx -b backup.gpx

# Convert and delete source files
nmea2gpx "*.nmea" -o output.gpx --delete-source
```

## Coordinate Validation Details

### Validation Functions

The tool provides several validation functions:

```python
from nmea2gpx import (
    validate_latitude,
    validate_longitude, 
    validate_coordinates,
    detect_gps_errors,
    should_reject_coordinates
)

# Basic validation
is_valid = validate_coordinates(45.0, -120.0)  # True
is_valid = validate_coordinates(91.0, -120.0)  # False

# GPS error detection
errors = detect_gps_errors(0.0, 0.0)
# Returns: ['Zero coordinates detected (likely GPS startup)', 
#          'Coordinates at null island (0,0) - likely invalid', ...]

# Strict validation
should_reject = should_reject_coordinates(0.0, 0.0, strict=True)  # True
```

### Common GPS Issues Detected

1. **Zero Coordinates (0,0)**
   - Often indicates GPS startup or initialization
   - Located at "null island" in the Atlantic Ocean
   - Usually invalid for real GPS data

2. **Coordinates Very Close to Zero**
   - Coordinates with absolute values < 0.0001°
   - May indicate GPS initialization or poor signal

3. **Pole Coordinates**
   - Latitude exactly at 90° or -90°
   - Valid but rare - worth verifying

4. **180th Meridian**
   - Longitude exactly at 180° or -180°
   - Valid but rare - worth verifying

5. **Equator/Prime Meridian**
   - Latitude exactly at 0° (equator)
   - Longitude exactly at 0° (prime meridian)
   - These are normal and valid coordinates (not flagged as errors)

## Testing

Run the coordinate validation tests:

```bash
python3 test_coordinate_validation.py
```

Run the null byte handling tests:

```bash
python3 test_null_handling.py
```

## Null Byte Handling

The tool automatically handles NMEA files that are preallocated and padded with null bytes (0x00):

- **Automatic Removal**: Null bytes are automatically removed from all input lines
- **Checksum Validation**: Checksums are calculated correctly after null byte removal
- **Raw Output**: When using `--raw-output`, null bytes are also removed from the concatenated output
- **Empty Line Filtering**: Lines that become empty after null removal are automatically skipped

This feature is particularly useful for GPS devices that create preallocated files with null padding.

## Supported NMEA Sentences

- **RMC** (Recommended Minimum Navigation Information)
- **GGA** (Global Positioning System Fix Data)
- **GSA** (GPS DOP and Active Satellites)
- **VTG** (Track Made Good and Ground Speed)
- **GSV** (Satellites in View)

## Output Format

The tool generates standard GPX 1.1 files with:
- Track points with latitude, longitude, and elevation
- Timestamps in ISO 8601 format
- NMEA extensions for additional data
- Garmin TrackPointExtension v2 for compatibility

## Logging

The tool provides detailed logging:
- **INFO**: File processing and conversion progress
- **WARNING**: Coordinate validation issues
- **ERROR**: File processing errors
- **DEBUG**: Detailed parsing information (with -v flag)

## License

This tool is part of the pygotu project and is released under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit issues and pull requests. 