import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:file_selector/file_selector.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter_bluetooth_serial/flutter_bluetooth_serial.dart';
import 'package:permission_handler/permission_handler.dart';

void main() => runApp(const NimbusApp());

class NimbusApp extends StatelessWidget {
  const NimbusApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Nimbus Weighing',
      theme: ThemeData(
        brightness: Brightness.light,
        primaryColor: Colors.blueAccent,
        scaffoldBackgroundColor: Colors.grey[50], 
        useMaterial3: true,
        appBarTheme: const AppBarTheme(backgroundColor: Colors.white, foregroundColor: Colors.black, elevation: 1),
      ),
      home: const MainWorkflowScreen(),
    );
  }
}

class MainWorkflowScreen extends StatefulWidget {
  const MainWorkflowScreen({super.key});
  @override
  State<MainWorkflowScreen> createState() => _MainWorkflowScreenState();
}

class _MainWorkflowScreenState extends State<MainWorkflowScreen> {
  final String baseUrl = "http://35.175.113.81:8000"; // AWS Cloud IP
  List<dynamic> products = [];
  bool isLoading = false;
  int currentIndex = 0;
  
  // Local Bluetooth State
  BluetoothConnection? connection;
  BluetoothDevice? server;
  String scaleStatus = "Disconnected";
  double currentWeight = 0.0;
  String? connectedPort;
  bool isFileUploaded = false;
  String scaleDiagnosticMsg = "Waiting for connection...";
  String _messageBuffer = ""; 

  @override
  void dispose() {
    connection?.dispose();
    super.dispose();
  }

  void startStatusTimer() {
    // We no longer pull scale status from the backend. 
    // The Bluetooth connection stream handles this now.
  }

  Future<void> scanAndConnect() async {
    // 1. Check Permissions
    Map<Permission, PermissionStatus> statuses = await [
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.location,
    ].request();

    if (statuses[Permission.bluetoothScan] != PermissionStatus.granted ||
        statuses[Permission.bluetoothConnect] != PermissionStatus.granted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Bluetooth Permissions Denied"))
      );
      return;
    }

    try {
      // 2. Get Paired Devices
      List<BluetoothDevice> bondedDevices = await FlutterBluetoothSerial.instance.getBondedDevices();
      
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text("Select Bluetooth Scale"),
          content: SizedBox(
            width: double.maxFinite,
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: bondedDevices.length,
              itemBuilder: (context, i) => ListTile(
                leading: const Icon(Icons.bluetooth),
                title: Text(bondedDevices[i].name ?? "Unknown Device"),
                subtitle: Text(bondedDevices[i].address),
                onTap: () {
                  Navigator.pop(context);
                  _connectToDevice(bondedDevices[i]);
                },
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context), 
              child: const Text("CANCEL")
            ),
          ],
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Error: $e")));
    }
  }

  void _connectToDevice(BluetoothDevice device) async {
    setState(() {
      scaleStatus = "Connecting...";
      scaleDiagnosticMsg = "Linking to ${device.name}...";
    });

    try {
      connection = await BluetoothConnection.toAddress(device.address);
      setState(() {
        server = device;
        scaleStatus = "Connected";
        scaleDiagnosticMsg = "Directly connected to ${device.name}";
        connectedPort = device.name;
      });

      connection!.input!.listen(_onDataReceived).onDone(() {
        setState(() {
          scaleStatus = "Disconnected";
          scaleDiagnosticMsg = "Connection lost.";
          connection = null;
        });
      });
    } catch (e) {
      setState(() {
        scaleStatus = "Failed";
        scaleDiagnosticMsg = "Could not connect.";
      });
    }
  }

  void _onDataReceived(Uint8List data) {
    // Convert bytes to string and buffer it
    String dataString = String.fromCharCodes(data);
    _messageBuffer += dataString;

    // Check for newline (assuming scale sends \n or \r)
    if (_messageBuffer.contains('\n') || _messageBuffer.contains('\r')) {
      final lines = _messageBuffer.split(RegExp(r'[\n\r]'));
      // Last element might be incomplete, keep it in buffer
      _messageBuffer = lines.last;
      
      // Process the second-to-last complete line
      for (int i = 0; i < lines.length - 1; i++) {
        String line = lines[i].trim();
        if (line.isNotEmpty) {
          _parseWeightLine(line);
        }
      }
    }
  }

  void _parseWeightLine(String line) {
    // Try to extract a number from the line (e.g., "1.23 kg" -> 1.23)
    final regExp = RegExp(r"[-+]?\d*\.?\d+");
    final match = regExp.firstMatch(line);
    if (match != null) {
      setState(() {
        currentWeight = double.tryParse(match.group(0)!) ?? 0.0;
        
        // AUTO-UPDATE CURRENT ITEM WEIGHT
        if (products.isNotEmpty && currentWeight > 0.05) {
          products[currentIndex]['Weight(gm)'] = currentWeight.toStringAsFixed(2);
        }
      });
    }
  }

  Future<void> pickAndUploadFile() async {
    try {
      final XFile? file = await openFile(
        acceptedTypeGroups: <XTypeGroup>[
          const XTypeGroup(label: 'Excel/CSV', extensions: <String>['csv', 'xlsx']),
        ],
      );
      
      if (file != null) {
        setState(() => isLoading = true);
        try {
          var request = http.MultipartRequest('POST', Uri.parse("$baseUrl/upload"));
          
          // Web compatibility: use fromBytes instead of fromPath
          final bytes = await file.readAsBytes();
          request.files.add(http.MultipartFile.fromBytes(
            'file',
            bytes,
            filename: file.name,
          ));
          
          var res = await request.send();
          if (res.statusCode == 200) {
            setState(() => isFileUploaded = true);
            fetchProducts();
          }
        } catch (e) {
          setState(() => isLoading = false);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Upload failed: $e")));
        }
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Picker error: $e")));
    }
  }

  Future<void> fetchProducts() async {
    setState(() => isLoading = true);
    final res = await http.get(Uri.parse("$baseUrl/products"));
    if (res.statusCode == 200) {
      setState(() {
        products = json.decode(res.body);
        isLoading = false;
      });
    }
  }

  Future<void> captureWeight({String? manualWeight}) async {
    final orderId = products[currentIndex]['Order ID*'];
    String url = "$baseUrl/capture/$orderId";
    if (manualWeight != null) url += "?manual_weight=$manualWeight";
    
    final res = await http.post(Uri.parse(url));
    if (res.statusCode == 200) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Captured ${manualWeight ?? 'Live Weight'} Successfully!")));
      final data = json.decode(res.body);
      setState(() => products[currentIndex]['Weight(gm)'] = data['weight'].toString());
    }
  }

  String searchQueries = "";

  @override
  Widget build(BuildContext context) {
    if (!isFileUploaded) return _buildSetupScreen();
    if (isLoading) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (products.isEmpty) return _buildSetupScreen();

    final filteredProducts = products.where((p) => 
      p['Order ID*'].toString().contains(searchQueries)).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text("Nimbus Excel View"),
        actions: [
          IconButton(
            icon: const Icon(Icons.download), 
            onPressed: exportReport,
            tooltip: "Export Excel",
          ),
        ],
      ),
      body: Column(
        children: [
          _buildStatusHeader(),
          _buildSearchBar(),
          Expanded(child: _buildExcelTable(filteredProducts)),
          _buildSelectionPanel(),
        ],
      ),
    );
  }

  Future<void> exportReport() async {
    final res = await http.get(Uri.parse("$baseUrl/export"));
    final tempDir = await getTemporaryDirectory();
    final file = File('${tempDir.path}/final_report.csv');
    await file.writeAsBytes(res.bodyBytes);
    Share.shareXFiles([XFile(file.path)], text: 'Nimbus Report');
  }

  Widget _buildSearchBar() {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5)],
      ),
      child: TextField(
        decoration: InputDecoration(
          hintText: "Search Order ID...",
          hintStyle: TextStyle(color: Colors.grey[400]),
          prefixIcon: Icon(Icons.search, color: Colors.grey[400]),
          border: InputBorder.none,
          contentPadding: const EdgeInsets.symmetric(vertical: 15),
        ),
        onChanged: (v) => setState(() => searchQueries = v),
      ),
    );
  }

  Widget _buildExcelTable(List<dynamic> list) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: Colors.grey[300]!),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: SingleChildScrollView(
          scrollDirection: Axis.vertical,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              showCheckboxColumn: false,
              headingRowColor: WidgetStateProperty.all(Colors.blue.withOpacity(0.05)),
              dataRowColor: WidgetStateProperty.resolveWith((states) {
                if (states.contains(WidgetState.selected)) return Colors.blue.withOpacity(0.2);
                return null;
              }),
              border: TableBorder.all(color: Colors.grey[200]!, width: 1),
              columns: const [
                DataColumn(label: Text("ID", style: TextStyle(fontWeight: FontWeight.bold))),
                DataColumn(label: Text("Pcs", style: TextStyle(fontWeight: FontWeight.bold))),
                DataColumn(label: Text("H", style: TextStyle(fontWeight: FontWeight.bold))),
                DataColumn(label: Text("B", style: TextStyle(fontWeight: FontWeight.bold))),
                DataColumn(label: Text("L", style: TextStyle(fontWeight: FontWeight.bold))),
                DataColumn(label: Text("Weight (gm)", style: TextStyle(fontWeight: FontWeight.bold))),
              ],
              rows: list.asMap().entries.map((entry) {
                final i = entry.key;
                final p = entry.value;
                final isSelected = currentIndex == i;
                return DataRow(
                  selected: isSelected,
                  color: WidgetStateProperty.all(i % 2 == 0 ? Colors.white : Colors.grey[50]),
                  onSelectChanged: (_) => setState(() => currentIndex = i),
                  cells: [
                    DataCell(Text(p['Order ID*'].toString())),
                    DataCell(Text(p['Total Products Count'].toString())),
                    DataCell(Text(p['Height(cm)'].toString())),
                    DataCell(Text(p['Breadth(cm)'].toString())),
                    DataCell(Text(p['Length(cm)'].toString())),
                    DataCell(
                      GestureDetector(
                        onTap: () {
                          final ctrl = TextEditingController(text: p['Weight(gm)'] ?? "0");
                          showDialog(
                            context: context,
                            builder: (context) => AlertDialog(
                              title: const Text("Edit Weight (gm)"),
                              content: TextField(controller: ctrl, keyboardType: TextInputType.number),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(context), child: const Text("CANCEL")),
                                ElevatedButton(
                                  onPressed: () {
                                    setState(() => p['Weight(gm)'] = ctrl.text);
                                    captureWeight(manualWeight: ctrl.text);
                                    Navigator.pop(context);
                                  }, 
                                  child: const Text("SAVE"),
                                ),
                              ],
                            ),
                          );
                        },
                        child: Text(p['Weight(gm)'] ?? "0", style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.blueAccent)),
                      ),
                    ),
                  ],
                );
              }).toList(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSelectionPanel() {
    if (products.isEmpty) return const SizedBox();
    final item = products[currentIndex];
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: const Offset(0, -5))],
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("ORDER ID: ${item['Order ID*']}", style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                  Text("L:${item['Length(cm)']} B:${item['Breadth(cm)']} H:${item['Height(cm)']}", style: TextStyle(color: Colors.grey[600], fontSize: 12)),
                ],
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(color: Colors.blue.withOpacity(0.1), borderRadius: BorderRadius.circular(20)),
                child: Text("${currentIndex + 1} / ${products.length}", style: const TextStyle(color: Colors.blue, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const SizedBox(height: 15),
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.blueAccent, 
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                  icon: const Icon(Icons.scale),
                  label: const Text("CAPTURE WEIGHT", style: TextStyle(fontWeight: FontWeight.bold)),
                  onPressed: captureWeight,
                ),
              ),
              const SizedBox(width: 12),
              Material(
                color: Colors.grey[100],
                borderRadius: BorderRadius.circular(12),
                child: InkWell(
                  onTap: () async {
                    // AUTO-SAVE BEFORE NEXT
                    await captureWeight(manualWeight: products[currentIndex]['Weight(gm)']);
                    setState(() { if (currentIndex < products.length - 1) currentIndex++; });
                  },
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
                    child: const Icon(Icons.arrow_forward_ios, size: 18),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSetupScreen() {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text("Om Vinayaka Garments", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18, color: Colors.blueAccent)),
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.white,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24.0, vertical: 40.0),
        child: Column(
          children: [
            const Text(
              "Om Vinayaka Garments",
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              "Follow the steps below to start weighing",
              style: TextStyle(fontSize: 14, color: Colors.grey),
            ),
            const SizedBox(height: 50),
            _buildSetupButton(
              "CONNECT SCALE", 
              Icons.bluetooth_searching, 
              connectedPort != null ? Colors.green : Colors.blueAccent,
              scanAndConnect,
              step: "STEP 1",
              subtitle: connectedPort != null ? "Connected to $connectedPort" : "Scan and pair with HC-05",
            ),
            const SizedBox(height: 20),
            _buildSetupButton(
              "UPLOAD CSV FILE", 
              Icons.file_copy_rounded, 
              Colors.orange,
              pickAndUploadFile,
              step: "STEP 2",
              subtitle: "Import your NimbusPost order CSV",
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSetupButton(String title, IconData icon, Color color, VoidCallback onPressed, {required String step, required String subtitle}) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: [BoxShadow(color: color.withOpacity(0.1), blurRadius: 20, spreadRadius: 5)],
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(20),
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(15),
                  ),
                  child: Icon(icon, color: color, size: 30),
                ),
                const SizedBox(width: 20),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(step, style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: color, letterSpacing: 1)),
                      Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                      Text(subtitle, style: TextStyle(fontSize: 12, color: Colors.grey[600])),
                    ],
                  ),
                ),
                Icon(Icons.arrow_forward_ios, size: 16, color: Colors.grey[400]),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildStatusHeader() {
    return Container(
      margin: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5)],
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: scaleStatus == "Connected" ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
                  shape: BoxShape.circle,
                ),
                child: Icon(Icons.bluetooth, color: scaleStatus == "Connected" ? Colors.green : Colors.red, size: 20),
              ),
              const SizedBox(width: 10),
              Text(scaleStatus, style: TextStyle(fontWeight: FontWeight.bold, color: scaleStatus == "Connected" ? Colors.green : Colors.red)),
              const Spacer(),
              Text("${currentWeight.toStringAsFixed(2)} gm", style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.blueAccent)),
            ],
          ),
          const SizedBox(height: 8),
          Text(scaleDiagnosticMsg, style: TextStyle(fontSize: 11, color: Colors.grey[600], fontStyle: FontStyle.italic)),
        ],
      ),
    );
  }

  Widget _buildDim(String l, String val) {
    return Column(children: [Text(l, style: const TextStyle(color: Colors.grey)), Text("$val cm", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold))]);
  }
}
