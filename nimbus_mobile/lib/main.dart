import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:file_selector/file_selector.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'dart:io';

void main() => runApp(const NimbusApp());

class NimbusApp extends StatelessWidget {
  const NimbusApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Nimbus Weighing',
      theme: ThemeData(
        brightness: Brightness.dark,
        primaryColor: Colors.blueAccent,
        useMaterial3: true,
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
  final String baseUrl = "http://192.168.1.45:8000"; // Computer IP
  List<dynamic> products = [];
  bool isLoading = false;
  int currentIndex = 0;
  String scaleStatus = "Disconnected";
  double currentWeight = 0.0;
  String? connectedPort;
  bool isFileUploaded = false;
  String scaleDiagnosticMsg = "Waiting for connection...";

  @override
  void initState() {
    super.initState();
    startStatusTimer();
  }

  void startStatusTimer() {
    Future.doWhile(() async {
      await Future.delayed(const Duration(seconds: 2));
      if (!mounted) return false;
      try {
        final res = await http.get(Uri.parse("$baseUrl/scale_status"));
        if (res.statusCode == 200) {
          final data = json.decode(res.body);
          setState(() {
            scaleStatus = data['connected'] ? "Connected" : "Disconnected";
            currentWeight = data['weight'];
            connectedPort = data['port'];
            scaleDiagnosticMsg = data['status_log'] ?? "No signal...";
          });
        }
      } catch (_) {}
      return true;
    });
  }

  Future<void> scanAndConnect() async {
    try {
      final res = await http.get(Uri.parse("$baseUrl/scan"));
      final List<dynamic> ports = json.decode(res.body);
      
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text("Select Bluetooth/Serial Port"),
          content: SizedBox(
            width: double.maxFinite,
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: ports.length,
              itemBuilder: (context, i) => ListTile(
                title: Text(ports[i]['port']),
                subtitle: Text(ports[i]['desc']),
                onTap: () async {
                  await http.post(Uri.parse("$baseUrl/connect/${ports[i]['port']}"));
                  if (mounted) {
                    Navigator.pop(context);
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text("Connected to ${ports[i]['port']} Successfully!"),
                        backgroundColor: Colors.green,
                      ),
                    );
                  }
                },
              ),
            ),
          ),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Scan Failed")));
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

  Future<void> captureWeight() async {
    final orderId = products[currentIndex]['Order ID*'];
    final res = await http.post(Uri.parse("$baseUrl/capture/$orderId"));
    if (res.statusCode == 200) {
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
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      child: TextField(
        decoration: InputDecoration(
          hintText: "Search Order ID...",
          prefixIcon: const Icon(Icons.search),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
          contentPadding: const EdgeInsets.all(5),
        ),
        onChanged: (v) => setState(() => searchQueries = v),
      ),
    );
  }

  Widget _buildExcelTable(List<dynamic> list) {
    return SingleChildScrollView(
      scrollDirection: Axis.vertical,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: DataTable(
          showCheckboxColumn: false,
          headingRowColor: WidgetStateProperty.all(Colors.blue.withOpacity(0.1)),
          columns: const [
            DataColumn(label: Text("ID")),
            DataColumn(label: Text("Pcs")),
            DataColumn(label: Text("L")),
            DataColumn(label: Text("B")),
            DataColumn(label: Text("H")),
            DataColumn(label: Text("Weight (gm)")),
          ],
          rows: list.asMap().entries.map((entry) {
            final i = entry.key;
            final p = entry.value;
            final isSelected = currentIndex == i;
            return DataRow(
              selected: isSelected,
              onSelectChanged: (_) => setState(() => currentIndex = i),
              cells: [
                DataCell(Text(p['Order ID*'].toString())),
                DataCell(Text(p['Total Products Count'].toString())),
                DataCell(Text(p['Length(cm)'].toString())),
                DataCell(Text(p['Breadth(cm)'].toString())),
                DataCell(Text(p['Height(cm)'].toString())),
                DataCell(Text(p['Weight(gm)'] ?? "0", style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.blueAccent))),
              ],
            );
          }).toList(),
        ),
      ),
    );
  }

  Widget _buildSelectionPanel() {
    if (products.isEmpty) return const SizedBox();
    final item = products[currentIndex];
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.3), blurRadius: 10)],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Text("ITEM: ${item['Order ID*']}", style: const TextStyle(fontWeight: FontWeight.bold)),
              const Spacer(),
              Text("DIM: ${item['Length(cm)']} x ${item['Breadth(cm)']} x ${item['Height(cm)']}"),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.blueAccent, 
                    padding: const EdgeInsets.all(15)
                  ),
                  icon: const Icon(Icons.scale),
                  label: const Text("CAPTURE WEIGHT"),
                  onPressed: captureWeight,
                ),
              ),
              const SizedBox(width: 10),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.grey[800], padding: const EdgeInsets.all(15)),
                onPressed: () => setState(() {
                  if (currentIndex < products.length - 1) currentIndex++;
                }),
                child: const Text("NEXT"),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSetupScreen() {
    return Scaffold(
      appBar: AppBar(title: const Text("Nimbus Scale Setup")),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _buildSetupButton(
                "1. CONNECT SCALE", 
                Icons.bluetooth_searching, 
                connectedPort != null ? Colors.green : Colors.blue,
                scanAndConnect,
                subtitle: connectedPort != null ? "Connected to $connectedPort" : "Scan available ports",
              ),
              const SizedBox(height: 30),
              _buildSetupButton(
                "2. UPLOAD CSV FILE", 
                Icons.file_upload, 
                Colors.orange,
                pickAndUploadFile,
                subtitle: "Select report file from your phone",
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSetupButton(String title, IconData icon, Color color, VoidCallback onPressed, {String? subtitle}) {
    return InkWell(
      onTap: onPressed,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          border: Border.all(color: color, width: 2),
          borderRadius: BorderRadius.circular(15),
        ),
        child: Row(
          children: [
            Icon(icon, size: 40, color: color),
            const SizedBox(width: 20),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: color)),
                if (subtitle != null) Text(subtitle, style: const TextStyle(fontSize: 12, color: Colors.grey)),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusHeader() {
    return Container(
      color: scaleStatus == "Connected" ? Colors.green.withOpacity(0.2) : Colors.red.withOpacity(0.2),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.bluetooth, color: scaleStatus == "Connected" ? Colors.green : Colors.red),
              const SizedBox(width: 10),
              Text(scaleStatus, style: const TextStyle(fontWeight: FontWeight.bold)),
              const Spacer(),
              Text("${currentWeight.toStringAsFixed(2)} KG", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.blue)),
            ],
          ),
          const Divider(height: 10),
          Text(scaleDiagnosticMsg, style: const TextStyle(fontSize: 12, color: Colors.yellow, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Widget _buildDim(String l, String val) {
    return Column(children: [Text(l, style: const TextStyle(color: Colors.grey)), Text("$val cm", style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold))]);
  }
}
