// MIT: compilation interfaces only. No Rhino or Grasshopper implementation is included.
using System;
using System.Collections.Generic;

namespace Grasshopper.Kernel
{
    public enum GH_ParamAccess { item }
    public interface IGH_DataAccess
    {
        bool GetData<T>(int index, ref T value);
        void SetData(int index, object value);
    }
    public sealed class Parameter { public bool Optional { get; set; } }
    public abstract class GH_Component
    {
        protected GH_Component(string name, string nick, string description, string category, string subcategory) { }
        protected abstract void RegisterInputParams(GH_InputParamManager manager);
        protected abstract void RegisterOutputParams(GH_OutputParamManager manager);
        protected abstract void SolveInstance(IGH_DataAccess data);
        protected abstract System.Drawing.Bitmap Icon { get; }
        public abstract Guid ComponentGuid { get; }
        public void Evaluate(IGH_DataAccess data) { SolveInstance(data); }
        public class GH_InputParamManager
        {
            public Parameter this[int index] { get { return new Parameter(); } }
            public void AddTextParameter(string a, string b, string c, GH_ParamAccess d) { }
            public void AddNumberParameter(string a, string b, string c, GH_ParamAccess d) { }
            public void AddIntegerParameter(string a, string b, string c, GH_ParamAccess d) { }
            public void AddBooleanParameter(string a, string b, string c, GH_ParamAccess d) { }
        }
        public class GH_OutputParamManager
        {
            public void AddNumberParameter(string a, string b, string c, GH_ParamAccess d) { }
        }
    }
}

// The scoped components never call Rhino geometry. Throwing stubs make this
// restriction executable if an upstream dependency changes unexpectedly.
namespace Rhino.Geometry
{
    public struct Point3d
    {
        public double X, Y, Z;
        public Point3d(double x, double y, double z) { X = x; Y = y; Z = z; }
    }
    public struct Vector3d { public static Vector3d ZAxis => new Vector3d(); }
    public enum CurveOffsetCornerStyle { None }
    public class Curve
    {
        public PolylineCurve ToPolyline(double a, double b, double c, double d, double e, double f, double g, double h, bool i)
            => throw new NotSupportedException("Rhino geometry is outside the continuous oracle");
    }
    public class PolylineCurve : Curve
    {
        public PolylineCurve(List<Point3d> points) { throw new NotSupportedException("Rhino geometry is outside the continuous oracle"); }
        public void MakeClosed(double tolerance) { throw new NotSupportedException(); }
        public Curve[] Offset(Point3d p, Vector3d v, double d, double t, CurveOffsetCornerStyle s) => throw new NotSupportedException();
        public Point3d Point(int index) => throw new NotSupportedException();
    }
}

namespace GHEnergyPlus.Properties
{
    internal static class Resources
    {
        internal static System.Drawing.Bitmap opti_1to3 => null;
        internal static System.Drawing.Bitmap opti_4to8 => null;
        internal static System.Drawing.Bitmap opti_9 => null;
        internal static System.Drawing.Bitmap opti_10 => null;
        internal static System.Drawing.Bitmap opti_13 => null;
    }
}
